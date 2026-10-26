import json
import requests
import telebot

# Читаем настройки, прошлые проекты и инструкцию для нейросети.
try:
    with open("private/bot_settings.json", encoding="utf-8") as file:
        settings = json.load(file)
    with open("private/projects.txt", encoding="utf-8") as file:
        projects = file.read()
    with open("prompt.txt", encoding="utf-8") as file:
        instructions = file.read()
except OSError as error:
    raise SystemExit("Не удалось открыть файл: " + str(error.filename))
except (json.JSONDecodeError, UnicodeError):
    raise SystemExit("Проверьте JSON в настройках и кодировку UTF-8 в текстовых файлах.")

if not isinstance(settings, dict):
    raise SystemExit("Настройки должны быть объектом JSON: названия полей и их значения.")
if not settings.get("telegram_bot_token"):
    raise SystemExit("Не указан токен Telegram.")
if not isinstance(settings.get("allowed_user_ids"), list):
    raise SystemExit("allowed_user_ids должен быть списком числовых Telegram ID.")
if not projects.strip() or not instructions.strip():
    raise SystemExit("База проектов и инструкция для нейросети должны содержать текст.")
try:
    bot = telebot.TeleBot(settings["telegram_bot_token"], threaded=False)
except (ValueError, TypeError, AttributeError):
    raise SystemExit("Неверный формат токена Telegram.")

REQUEST_TIMEOUT = 90
MAX_OUTPUT_TOKENS = 2000
MESSAGE_CHUNK_SIZE = 2000


def get_estimate(task):
    if not isinstance(task, str) or not task.strip():
        raise ValueError("Пришлите ТЗ непустым текстовым сообщением.")
    if not settings.get("openrouter_api_key"):
        raise ValueError("Не заполнен ключ OpenRouter в настройках.")
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": "Bearer " + settings["openrouter_api_key"]},
        json={
            "model": settings["openrouter_model"],
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": "Прошлые проекты:\n" + projects + "\nНовое ТЗ:\n" + task},
            ],
            "max_tokens": MAX_OUTPUT_TOKENS,
            "provider": {"data_collection": "deny", "zdr": True},
        },
        timeout=REQUEST_TIMEOUT,
        allow_redirects=False,
    )
    response.raise_for_status()
    choice = response.json()["choices"][0]
    answer = choice["message"]["content"]
    if choice["finish_reason"] != "stop" or not isinstance(answer, str) or not answer.strip():
        raise ValueError("Нейросеть вернула пустой или незавершённый ответ. Оценка не сохранена.")
    return answer


def reply(message):
    if message.chat.type != "private":
        return
    if message.from_user.id not in settings["allowed_user_ids"]:
        bot.send_message(message.chat.id, "Доступ закрыт. Твой Telegram ID: " + str(message.from_user.id))
        return
    if message.text.startswith("/"):
        bot.send_message(message.chat.id, "Пришли обезличенное ТЗ одним текстовым сообщением.")
        return
    answer = ""
    try:
        answer = get_estimate(message.text)
        with open("private/answers.txt", "a", encoding="utf-8") as file:
            file.write("\nТЗ:\n" + message.text + "\nОтвет:\n" + answer + "\n")
    except requests.HTTPError as error:
        if error.response.status_code == 429:
            bot.send_message(message.chat.id, "OpenRouter: HTTP 429. Сервис ограничил запросы к модели. Попробуйте позже или выберите другую модель.")
        else:
            bot.send_message(message.chat.id, "OpenRouter: HTTP " + str(error.response.status_code) + ". Проверьте ключ, баланс или доступность модели.")
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        bot.send_message(message.chat.id, "Некорректны настройки или формат ответа OpenRouter.")
    except requests.RequestException:
        bot.send_message(message.chat.id, "OpenRouter недоступен: проверьте сеть или повторите запрос позже.")
    except ValueError as error:
        bot.send_message(message.chat.id, str(error))
    except OSError:
        bot.send_message(message.chat.id, "Ответ получен, но его не удалось записать в private/answers.txt. Проверьте доступ к файлу.")
    if answer:
        for start in range(0, len(answer), MESSAGE_CHUNK_SIZE):
            bot.send_message(message.chat.id, answer[start:start + MESSAGE_CHUNK_SIZE])


bot.register_message_handler(reply, content_types=["text"])
bot.infinity_polling(skip_pending=True, allowed_updates=["message"])
