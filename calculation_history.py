"""Отдельный неизменяемый JSON-файл для каждого запроса к модели."""

import json
from pathlib import Path
from tempfile import NamedTemporaryFile


def read_calculation(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("text"), str):
        raise ValueError("Повреждён файл сохранённого расчёта.")
    return data


def save_calculation(path, data):
    path = Path(path)
    if path.exists():
        raise ValueError("Этот запрос уже сохранён. Предыдущий расчёт не изменён.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary_path = Path(file.name)
            json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
            file.write("\n")
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
