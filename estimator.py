"""Данные для модели, проверка её ответа и понятный текст результата."""

import json
from pathlib import Path


def load_history(path):
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("estimates"), list):
        raise ValueError("В истории нужен список estimates.")
    cases = []
    seen_ids = set()
    for row in data["estimates"]:
        if not isinstance(row, dict):
            raise ValueError("Запись истории должна быть объектом JSON.")
        for field in ("estimate_id", "developer_id", "task_title", "scope_summary", "specification_file"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f"В истории не заполнено поле {field}.")
        if row["estimate_id"] in seen_ids:
            raise ValueError("В истории повторяется estimate_id.")
        seen_ids.add(row["estimate_id"])
        if type(row.get("amount")) is not int or row["amount"] <= 0 or row.get("currency") != "RUB":
            raise ValueError("История должна содержать положительные целые цены в RUB.")
        if row.get("price_basis") != "full_specification" or row.get("price_source") != "developer":
            raise ValueError("Для истории требуется оценка разработчика за полное ТЗ.")
        filename = row["specification_file"]
        if Path(filename).name != filename:
            raise ValueError("Текст ТЗ должен находиться рядом с файлом истории.")
        specification = (path.parent / filename).read_text(encoding="utf-8")
        if not specification.strip():
            raise ValueError("В истории найдено пустое ТЗ.")
        cases.append({
            "estimate_id": row["estimate_id"], "developer_id": row["developer_id"],
            "task_title": row["task_title"], "summary": row["scope_summary"],
            "amount": row["amount"], "currency": "RUB", "specification": specification,
        })
    if not cases:
        raise ValueError("История пуста: сначала добавьте оценки разработчиков.")
    return cases


def build_messages(task, cases, profiles, instructions):
    if not isinstance(task, str) or not task.strip():
        raise ValueError("ТЗ не должно быть пустым.")
    payload = {"new_task": task, "history": cases, "profiles": profiles}
    return [
        {"role": "system", "content": instructions},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def validate_result(result, cases):
    if not isinstance(result, dict) or not isinstance(result.get("estimates"), list):
        raise ValueError("Модель не вернула список оценок.")
    owners = {case["estimate_id"]: case["developer_id"] for case in cases}
    expected = set(owners.values())
    received = set()
    priced = set()
    for row in result["estimates"]:
        if not isinstance(row, dict) or not isinstance(row.get("developer_id"), str):
            raise ValueError("Неверная запись в ответе модели.")
        developer = row["developer_id"]
        if developer not in expected or developer in received:
            raise ValueError("Модель добавила неизвестного или повторяющегося разработчика.")
        received.add(developer)
        if not isinstance(row.get("explanation"), str) or not row["explanation"].strip():
            raise ValueError("Модель не объяснила оценку.")
        if any(field not in row for field in ("price_min", "price", "price_max")):
            raise ValueError("Модель пропустила поля цен.")
        references = row.get("analogue_ids")
        if not isinstance(references, list) or any(
            not isinstance(item, str) or owners.get(item) != developer for item in references
        ):
            raise ValueError("Модель сослалась на неизвестную или чужую оценку.")
        prices = [row.get(field) for field in ("price_min", "price", "price_max")]
        if all(value is None for value in prices):
            continue
        if any(type(value) is not int or value <= 0 for value in prices):
            raise ValueError("Модель должна вернуть целые положительные цены или три null.")
        if not prices[0] <= prices[1] <= prices[2]:
            raise ValueError("Модель вернула противоречивый диапазон цен.")
        if not references:
            raise ValueError("Модель назвала цену без ссылки на историю разработчика.")
        priced.add(developer)
    if received != expected:
        raise ValueError("Модель пропустила разработчика из истории.")
    if "recommended_developer_id" not in result:
        raise ValueError("Модель пропустила поле рекомендации.")
    recommendation = result["recommended_developer_id"]
    if recommendation is not None and (not isinstance(recommendation, str) or recommendation not in priced):
        raise ValueError("Рекомендация не подтверждается рассчитанными оценками.")
    if not isinstance(result.get("recommendation_reason"), str) or not result["recommendation_reason"].strip():
        raise ValueError("Модель не объяснила рекомендацию.")
    if not isinstance(result.get("questions"), list) or any(not isinstance(item, str) for item in result["questions"]):
        raise ValueError("Неверный список уточняющих вопросов модели.")


def format_result(result, cases, profiles):
    names = {profile["developer_id"]: profile["display_name"] for profile in profiles}
    sources = {case["estimate_id"]: case for case in cases}
    lines = ["Предварительная оценка модели по истории, RUB."]
    for row in result["estimates"]:
        developer = row["developer_id"]
        lines.extend(["", names.get(developer, developer)])
        if row["price"] is None:
            lines.append("Недостаточно сопоставимых данных для цены.")
        else:
            lines.append(f"Ориентир: {row['price']:,} ₽".replace(",", " "))
            lines.append(f"Диапазон: {row['price_min']:,}–{row['price_max']:,} ₽".replace(",", " "))
        lines.append(row["explanation"])
        for estimate_id in row["analogue_ids"]:
            case = sources[estimate_id]
            lines.append(f"Аналог {estimate_id}: {case['task_title']} — {case['amount']} ₽.")
    recommendation = result["recommended_developer_id"]
    lines.extend(["", "Рекомендация: " + (names.get(recommendation, recommendation) if recommendation else "нет оснований выбрать одного")])
    lines.append(result["recommendation_reason"])
    if result["questions"]:
        lines.append("\nНужно уточнить:")
        lines.extend("• " + question for question in result["questions"])
    lines.append("\nДиапазон — предположение модели; его точность ещё не проверена.")
    return "\n".join(lines)
