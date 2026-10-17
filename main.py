"""Этап 1: создание и просмотр проектов BIT IT."""

from datetime import datetime
from pathlib import Path

from storage import load_data, save_data


DATA_PATH = Path(__file__).resolve().parent / "data" / "projects.json"


def show_projects(data):
    """Показываем проекты и их постоянные номера."""
    if not data["projects"]:
        print("Проектов пока нет.")
        return

    for project in data["projects"]:
        print(f"№{project['id']}: {project['name']}")
        if project["description"]:
            print(f"  {project['description']}")


def add_project(data, path):
    """Сначала сохраняем новую версию данных, затем возвращаем её в меню."""
    name = input("Название проекта: ").strip()
    if not name:
        print("Название не может быть пустым. Проект не добавлен.")
        return data
    description = input("Описание (можно пропустить): ").strip()

    project_id = max((project["id"] for project in data["projects"]), default=0) + 1
    project = {
        "id": project_id,
        "name": name,
        "description": description,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }

    new_data = data.copy()
    new_data["projects"] = data["projects"] + [project]
    save_data(path, new_data)
    print(f"Проект №{project_id} сохранён.")
    return new_data


def main(path=DATA_PATH):
    try:
        data = load_data(path)
    except (OSError, ValueError) as error:
        print(f"Не удалось открыть данные: {error}")
        print(f"Файл: {path}")
        return 1

    print("BIT IT — учёт проектов (этап 1)")
    while True:
        print("\n1 — Показать проекты\n2 — Добавить проект\n0 — Выход")
        choice = input("Действие: ").strip()
        if choice == "0":
            print("Работа завершена.")
            return 0
        if choice == "1":
            show_projects(data)
        elif choice == "2":
            try:
                data = add_project(data, path)
            except (OSError, ValueError) as error:
                print(f"Проект не сохранён: {error}")
        else:
            print("Выберите 0, 1 или 2.")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (EOFError, KeyboardInterrupt):
        print("\nРабота завершена.")
