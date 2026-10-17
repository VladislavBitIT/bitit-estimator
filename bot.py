"""Первый прототип: Telegram → ТЗ → OpenRouter → проверка → история."""

from datetime import datetime
import json
from pathlib import Path
import sys

import telebot

from calculation_history import read_calculation, save_calculation
from estimator import build_messages, format_result, load_history, validate_result
from openrouter_client import ask_model
from task_files import MAX_FILE_BYTES, extract_text


BASE_DIR = Path(__file__).resolve().parent


def load_settings():
    path = BASE_DIR / "private" / "settings.json"
    if not path.exists():
        path = BASE_DIR / "settings.example.json"
    settings = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(settings, dict):
        raise ValueError("Настройки должны быть объектом JSON.")
    for field in ("telegram_bot_token", "openrouter_api_key", "openrouter_model", "history_file", "profiles_file"):
        if not isinstance(settings.get(field), str):
            raise ValueError(f"В настройках поле {field} должно быть строкой.")
    ids = settings.get("allowed_user_ids")
    if not isinstance(ids, list) or any(type(item) is not int or item <= 0 for item in ids):
        raise ValueError("allowed_user_ids — список положительных целых Telegram ID.")
    for field in ("max_task_chars", "max_output_tokens"):
        if type(settings.get(field)) is not int or settings[field] <= 0:
            raise ValueError(f"Настройка {field} должна быть положительным целым числом.")
    return settings


def load_profiles(path, cases):
    profiles = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(profiles, list):
        raise ValueError("Профили разработчиков должны быть списком.")
    ids = []
    for profile in profiles:
        if not isinstance(profile, dict):
            raise ValueError("Неверный профиль разработчика.")
        for field in ("developer_id", "display_name", "level_note"):
            if not isinstance(profile.get(field), str) or not profile[field].strip():
                raise ValueError(f"В профиле не заполнено поле {field}.")
        if not isinstance(profile.get("skills"), list) or any(not isinstance(item, str) for item in profile["skills"]):
            raise ValueError("skills должен быть списком подтверждённых навыков.")
        ids.append(profile["developer_id"])
    if len(set(ids)) != len(ids) or set(ids) != {case["developer_id"] for case in cases}:
        raise ValueError("Профили должны соответствовать разработчикам из истории.")
    return profiles


def is_allowed(message, allowed_ids):
    return message.chat.type == "private" and message.from_user is not None and message.from_user.id in allowed_ids


def process_task(task, settings, cases, profiles, instructions, output_path):
    # Повтор доставки того же сообщения не вызывает ещё один платный запрос.
    if output_path.exists():
        return read_calculation(output_path)["text"]
    if not task.strip() or len(task) > settings["max_task_chars"]:
        raise ValueError(f"Пришлите непустое ТЗ до {settings['max_task_chars']} символов.")
    messages = build_messages(task, cases, profiles, instructions)
    result = ask_model(messages, settings)
    validate_result(result, cases)
    text = format_result(result, cases, profiles)
    save_calculation(output_path, {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "task": task, "model": settings["openrouter_model"], "result": result, "text": text,
        "history_snapshot": cases, "profiles_snapshot": profiles, "instructions": instructions,
    })
    return text


def create_bot(settings, cases, profiles, instructions):
    bot = telebot.TeleBot(settings["telegram_bot_token"], threaded=False)

    def send_text(chat_id, text):
        for start in range(0, len(text), 2000):
            bot.send_message(chat_id, text[start:start + 2000])

    @bot.message_handler(commands=["id"])
    def show_id(message):
        if message.chat.type == "private" and message.from_user is not None:
            bot.send_message(message.chat.id, f"Ваш Telegram ID: {message.from_user.id}")

    @bot.message_handler(commands=["start", "help"])
    def start(message):
        if not is_allowed(message, settings["allowed_user_ids"]):
            bot.send_message(message.chat.id, "Доступ не настроен. В личном чате команда /id покажет ваш ID для владельца бота.")
            return
        bot.send_message(message.chat.id,
            "Пришлите обезличенное ТЗ текстом или файлом TXT/DOCX до 2 МБ. "
            "Я сравню его с прошлыми работами и покажу ориентир цены. "
            "История ваших расчётов: /history. Команда /id — ваш ID.")

    @bot.message_handler(commands=["history"])
    def show_history(message):
        if not is_allowed(message, settings["allowed_user_ids"]):
            return
        paths = list((BASE_DIR / "data" / "calculations").glob(f"{message.from_user.id}_*.json"))
        paths.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        if not paths:
            bot.send_message(message.chat.id, "Ваших сохранённых расчётов пока нет.")
        for path in paths[:3]:
            try:
                saved = read_calculation(path)
                send_text(message.chat.id, saved["created_at"] + "\n" + saved["text"])
            except (OSError, ValueError, KeyError):
                bot.send_message(message.chat.id, "Один из файлов истории не удалось прочитать; он не изменён.")

    @bot.message_handler(content_types=["text", "document"])
    def estimate(message):
        if not is_allowed(message, settings["allowed_user_ids"]):
            return
        output_path = BASE_DIR / "data" / "calculations" / f"{message.from_user.id}_{message.message_id}.json"
        try:
            if message.content_type == "document":
                document = message.document
                if not document.file_size or document.file_size > MAX_FILE_BYTES:
                    raise ValueError("Пришлите файл не более 2 МБ.")
                if Path(document.file_name or "").suffix.lower() not in {".txt", ".docx"}:
                    raise ValueError("Поддерживаются файлы TXT и DOCX.")
                file = bot.get_file(document.file_id)
                task = extract_text(document.file_name, bot.download_file(file.file_path))
            else:
                task = message.text or ""
                if task.startswith("/"):
                    bot.send_message(message.chat.id, "Доступные команды: /start, /history, /id.")
                    return
            text = process_task(task, settings, cases, profiles, instructions, output_path)
        except (OSError, ValueError) as error:
            bot.send_message(message.chat.id, str(error))
            return
        send_text(message.chat.id, text)

    return bot


def main():
    settings = load_settings()
    cases = load_history(BASE_DIR / settings["history_file"])
    profiles = load_profiles(BASE_DIR / settings["profiles_file"], cases)
    instructions = (BASE_DIR / "model_instructions.txt").read_text(encoding="utf-8")
    if sys.argv[1:] == ["--check"]:
        print(f"Прочитано {len(cases)} примеров, профилей: {len(profiles)}. Инструкции загружены.")
        print("Локальная проверка завершена. Telegram и OpenRouter не вызывались.")
        return
    if not settings["telegram_bot_token"].strip():
        raise ValueError("Укажите telegram_bot_token в private/settings.json. Шаблон — settings.example.json.")
    bot = create_bot(settings, cases, profiles, instructions)
    print("Бот запускается. Для остановки нажмите Ctrl+C.")
    bot.infinity_polling(allowed_updates=["message"])


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(f"Не удалось запустить бота: {error}")
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("\nБот остановлен.")
