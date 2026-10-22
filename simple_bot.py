import json
import requests
import telebot

# Читаем настройки, прошлые проекты и инструкцию для нейросети.
with open("private/simple_settings.json", encoding="utf-8") as file:
    settings = json.load(file)
with open("private/simple_projects.txt", encoding="utf-8") as file:
    projects = file.read()
with open("simple_prompt.txt", encoding="utf-8") as file:
    instructions = file.read()

if not settings["telegram_bot_token"]:
    raise SystemExit("Впиши токен Telegram в private/simple_settings.json.")
bot = telebot.TeleBot(settings["telegram_bot_token"], threaded=False)


def get_estimate(task):
    """Отправляем новое ТЗ вместе с базой проектов и получаем текст ответа."""
    if not settings["openrouter_api_key"]:
        raise ValueError("Не заполнен ключ OpenRouter.")
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": "Bearer " + settings["openrouter_api_key"]},
        json={
            "model": settings["openrouter_model"],
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": "Прошлые проекты:\n" + projects + "\nНовое ТЗ:\n" + task},
            ],
            "max_tokens": 2000,
            "provider": {"data_collection": "deny", "zdr": True},
        },
        timeout=90,
        allow_redirects=False,
    )
    response.raise_for_status()
    choice = response.json()["choices"][0]
    if choice["finish_reason"] != "stop" or not choice["message"]["content"]:
        raise ValueError("Нейросеть не закончила ответ.")
    return choice["message"]["content"]


@bot.message_handler(content_types=["text"])
def reply(message):
    """Принимаем сообщение, проверяем доступ, сохраняем и отправляем оценку."""
    if message.chat.type != "private":
        return
    if message.text == "/id":
        bot.send_message(message.chat.id, "Твой Telegram ID: " + str(message.from_user.id))
        return
    if message.from_user.id not in settings["allowed_user_ids"]:
        bot.send_message(message.chat.id, "Доступ закрыт. Узнать свой ID: /id")
        return
    if message.text.startswith("/"):
        bot.send_message(message.chat.id, "Пришли обезличенное ТЗ одним текстовым сообщением.")
        return
    if not message.text.strip():
        return
    try:
        answer = get_estimate(message.text)
        with open("private/simple_answers.txt", "a", encoding="utf-8") as file:
            file.write("\nТЗ:\n" + message.text + "\nОтвет:\n" + answer + "\n")
        # Длинный ответ отправляем частями, чтобы он поместился в Telegram.
        for start in range(0, len(answer), 2000):
            bot.send_message(message.chat.id, answer[start:start + 2000])
    except Exception:
        bot.send_message(message.chat.id, "Не удалось обработать ТЗ. Проверь ключ OpenRouter, баланс, соединение и файл истории.")


print("Бот запущен. Остановка: Ctrl+C.")
bot.infinity_polling(skip_pending=True, allowed_updates=["message"])
