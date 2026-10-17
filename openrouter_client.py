"""Один HTTP-запрос к OpenRouter без автоматических платных повторов."""

import json

import requests


def ask_model(messages, settings):
    api_key = settings.get("openrouter_api_key", "").strip()
    model = settings.get("openrouter_model", "").strip()
    if not api_key or not model:
        raise ValueError("Укажите openrouter_api_key и openrouter_model в private/settings.json.")
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
            json={
                "model": model, "messages": messages,
                "response_format": {"type": "json_object"},
                "provider": {"require_parameters": True, "data_collection": "deny", "zdr": True},
                "max_tokens": settings["max_output_tokens"],
                "stream": False,
            },
            timeout=90,
            allow_redirects=False,
        )
    except requests.RequestException as error:
        raise ValueError("OpenRouter не ответил. Проверьте соединение; повторного запроса не было.") from error
    if response.status_code != 200:
        reasons = {401: "проверьте ключ", 402: "проверьте баланс и лимит ключа", 429: "достигнут лимит запросов"}
        reason = reasons.get(response.status_code, "проверьте модель и доступность провайдера с JSON-ответом и ZDR")
        raise ValueError(f"OpenRouter: HTTP {response.status_code}; {reason}.")
    try:
        choice = response.json()["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise ValueError("Ответ модели не завершён. Оценка не сохранена.")
        result = json.loads(choice["message"]["content"])
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("Модель вернула нечитаемый ответ. Оценка не сохранена.") from error
    return result
