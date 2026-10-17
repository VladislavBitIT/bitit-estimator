"""Синтетические примеры ассистента: рабочих данных здесь нет."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from main import add_project, main
from storage import load_data, save_data


def sample_data():
    return {
        "projects": [{
            "id": 1,
            "name": "Учебный проект",
            "description": "Вымышленный пример ассистента",
            "created_at": "2026-10-17T12:00:00+03:00",
        }],
    }


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "данные" / "projects.json"

    def test_first_launch_does_not_create_a_file(self):
        self.assertEqual(load_data(self.path), {"projects": []})
        self.assertFalse(self.path.exists())

    def test_save_and_reload_preserves_russian_text(self):
        data = sample_data()
        save_data(self.path, data)
        self.assertEqual(load_data(self.path), data)
        self.assertIn("Учебный проект", self.path.read_text(encoding="utf-8"))

    def test_corrupt_file_stops_the_app_without_overwriting(self):
        self.path.parent.mkdir()
        for content in (b'{"projects":', b"", b"\xff\xfe"):
            with self.subTest(content=content):
                self.path.write_bytes(content)
                with patch("builtins.print") as output:
                    self.assertEqual(main(self.path), 1)
                self.assertIn("Не удалось открыть данные", output.call_args_list[0].args[0])
                self.assertEqual(self.path.read_bytes(), content)

    def test_invalid_structure_is_rejected(self):
        self.path.parent.mkdir()
        cases = [[], {}, {"projects": None}, {"projects": ["ошибка"]}]
        for field, value in (("id", 0), ("id", True), ("name", "  "),
                             ("description", None), ("created_at", "")):
            data = sample_data()
            data["projects"][0][field] = value
            cases.append(data)
        repeated_id = sample_data()
        repeated_id["projects"].append(repeated_id["projects"][0].copy())
        cases.append(repeated_id)

        for data in cases:
            with self.subTest(data=data):
                content = json.dumps(data)
                self.path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_data(self.path)
                self.assertEqual(self.path.read_text(encoding="utf-8"), content)

    def test_failed_replacement_keeps_previous_file(self):
        original = sample_data()
        save_data(self.path, original)
        with patch("pathlib.Path.replace", side_effect=OSError("Проверка ошибки записи")):
            with self.assertRaises(OSError):
                save_data(self.path, {"projects": []})
        self.assertEqual(load_data(self.path), original)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_invalid_save_keeps_previous_file(self):
        original = sample_data()
        save_data(self.path, original)
        with self.assertRaises(ValueError):
            save_data(self.path, {"projects": [{"id": -1}]})
        self.assertEqual(load_data(self.path), original)

    def test_same_names_have_distinct_ids_after_restart(self):
        with patch("builtins.input", side_effect=["  Одинаковое название  ", ""]):
            with patch("builtins.print"):
                add_project({"projects": []}, self.path)
        reloaded = load_data(self.path)
        with patch("builtins.input", side_effect=["Одинаковое название", "Описание"]):
            with patch("builtins.print"):
                add_project(reloaded, self.path)
        self.assertEqual([project["id"] for project in load_data(self.path)["projects"]], [1, 2])

    def test_empty_name_does_not_create_data(self):
        with patch("builtins.input", return_value="  "):
            with patch("builtins.print"):
                data = add_project({"projects": []}, self.path)
        self.assertEqual(data, {"projects": []})
        self.assertFalse(self.path.exists())

    def test_failed_add_does_not_mutate_data_in_memory(self):
        data = sample_data()
        with patch("builtins.input", side_effect=["Другой учебный проект", ""]):
            with patch("main.save_data", side_effect=OSError("Ошибка записи")):
                with self.assertRaises(OSError):
                    add_project(data, self.path)
        self.assertEqual(data, sample_data())


if __name__ == "__main__":
    unittest.main()
