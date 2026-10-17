"""Чтение и сохранение локальных проектов в JSON."""

import json
from pathlib import Path
from tempfile import NamedTemporaryFile


def validate_data(data):
    """Не даём продолжить работу с непонятной структурой файла."""
    if not isinstance(data, dict) or not isinstance(data.get("projects"), list):
        raise ValueError("Ожидается объект JSON со списком projects.")

    seen_ids = set()
    for project in data["projects"]:
        if not isinstance(project, dict):
            raise ValueError("Каждый проект должен быть объектом JSON.")
        project_id = project.get("id")
        if type(project_id) is not int or project_id <= 0:
            raise ValueError("Номер проекта должен быть положительным целым числом.")
        if project_id in seen_ids:
            raise ValueError(f"Номер проекта {project_id} повторяется.")
        seen_ids.add(project_id)

        for field in ("name", "description", "created_at"):
            if not isinstance(project.get(field), str):
                raise ValueError(f"У проекта {project_id} поле {field} должно быть строкой.")
        if not project["name"].strip():
            raise ValueError(f"У проекта {project_id} пустое название.")
        if not project["created_at"].strip():
            raise ValueError(f"У проекта {project_id} отсутствует дата создания.")


def load_data(path):
    """При первом запуске возвращаем пустой список; плохой файл не заменяем."""
    path = Path(path)
    try:
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        return {"projects": []}
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ValueError(
            "Файл данных повреждён или сохранён не в UTF-8. "
            "Он не изменён; проверьте его или восстановите из своей резервной копии."
        ) from error

    validate_data(data)
    return data


def save_data(path, data):
    """Записываем новый файл целиком и только затем заменяем предыдущий."""
    validate_data(data)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as file:
            temporary_path = Path(file.name)
            json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
            file.write("\n")
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
