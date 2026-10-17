"""Проверка локальной цепочки без реальных ключей и сетевых запросов."""

from io import BytesIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

import telebot

from bot import create_bot, is_allowed, process_task
from calculation_history import read_calculation, save_calculation
from openrouter_client import ask_model
from task_files import extract_text
from test_estimator import sample_cases, sample_result


class BotFlowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "calculations" / "1_1.json"
        self.settings = {"max_task_chars": 100, "openrouter_model": "synthetic-model"}

    def test_calculation_survives_restart_and_duplicate_does_not_call_model(self):
        cases = sample_cases()
        with patch("bot.ask_model", return_value=sample_result()) as model:
            text = process_task("Учебное ТЗ", self.settings, cases, [], "Инструкции", self.path)
        self.assertEqual(model.call_count, 1)
        cases[0]["amount"] = 999
        saved = read_calculation(self.path)
        self.assertEqual(saved["history_snapshot"][0]["amount"], 10)
        self.assertEqual(saved["model"], "synthetic-model")
        with patch("bot.ask_model", side_effect=AssertionError("Повторный сетевой запрос")):
            self.assertEqual(process_task("Учебное ТЗ", self.settings, cases, [], "Новые инструкции", self.path), text)
        with self.assertRaises(ValueError):
            save_calculation(self.path, {"text": "Замена"})
        self.assertEqual(read_calculation(self.path), saved)

    def test_invalid_model_reply_is_not_saved(self):
        result = sample_result()
        result["estimates"][0]["analogue_ids"] = ["UNKNOWN"]
        with patch("bot.ask_model", return_value=result):
            with self.assertRaises(ValueError):
                process_task("ТЗ", self.settings, sample_cases(), [], "Инструкции", self.path)
        self.assertFalse(self.path.exists())

    def test_empty_and_oversized_tasks_do_not_call_model(self):
        with patch("bot.ask_model", side_effect=AssertionError("Сетевой запрос")):
            for task in ("  ", "x" * 101):
                with self.subTest(task=task):
                    with self.assertRaises(ValueError):
                        process_task(task, self.settings, sample_cases(), [], "Инструкции", self.path)

    def test_access_requires_both_private_chat_and_allowed_user(self):
        for chat_type, user_id, expected in (("private", 1, True), ("private", 2, False), ("group", 1, False)):
            message = SimpleNamespace(chat=SimpleNamespace(type=chat_type), from_user=SimpleNamespace(id=user_id))
            self.assertEqual(is_allowed(message, [1]), expected)
        self.assertFalse(is_allowed(SimpleNamespace(chat=SimpleNamespace(type="private"), from_user=None), [1]))

    def test_telegram_handler_does_not_process_unapproved_users_or_groups(self):
        settings = {"telegram_bot_token": "123456:synthetic-test-token", "allowed_user_ids": [1]}
        bot = create_bot(settings, sample_cases(), [], "Учебные инструкции")
        for user_id, chat_type, expected_calls in ((2, "private", 0), (1, "group", 0), (1, "private", 1)):
            with self.subTest(user_id=user_id, chat_type=chat_type):
                message = telebot.types.Message.de_json({
                    "message_id": 1, "date": 1,
                    "chat": {"id": user_id, "type": chat_type},
                    "from": {"id": user_id, "is_bot": False, "first_name": "Учебный пользователь"},
                    "text": "Учебное ТЗ",
                })
                with patch("bot.process_task", return_value="Учебный результат") as process:
                    with patch.object(bot, "send_message"):
                        with patch("telebot.apihelper._make_request", side_effect=AssertionError("Сетевой запрос")):
                            bot.process_new_messages([message])
                self.assertEqual(process.call_count, expected_calls)

    def test_missing_api_settings_do_not_send_request(self):
        with patch("openrouter_client.requests.post", side_effect=AssertionError("Сетевой запрос")):
            with self.assertRaises(ValueError):
                ask_model([], {"openrouter_api_key": "", "openrouter_model": ""})

    def test_server_error_has_no_automatic_retry(self):
        response = Mock(status_code=402)
        settings = {"openrouter_api_key": "synthetic-key", "openrouter_model": "synthetic-model", "max_output_tokens": 50}
        with patch("openrouter_client.requests.post", return_value=response) as request:
            with self.assertRaisesRegex(ValueError, "HTTP 402"):
                ask_model([], settings)
        self.assertEqual(request.call_count, 1)

    def test_truncated_model_reply_is_rejected(self):
        response = Mock(status_code=200)
        response.json.return_value = {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}
        settings = {"openrouter_api_key": "synthetic-key", "openrouter_model": "synthetic-model", "max_output_tokens": 50}
        with patch("openrouter_client.requests.post", return_value=response):
            with self.assertRaisesRegex(ValueError, "не завершён"):
                ask_model([], settings)

    def test_docx_paragraphs_and_table_text_are_extracted(self):
        buffer = BytesIO()
        xml = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Учебное ТЗ</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Текст таблицы</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>'
        with ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", xml)
        self.assertEqual(extract_text("example.docx", buffer.getvalue()), "Учебное ТЗ\nТекст таблицы")

    def test_invalid_or_unsupported_documents_are_rejected(self):
        for filename, content in (("broken.docx", b"not a ZIP"), ("example.pdf", b"PDF"), ("empty.txt", b"  "), ("wrong.txt", b"\xff")):
            with self.subTest(filename=filename):
                with self.assertRaises(ValueError):
                    extract_text(filename, content)


if __name__ == "__main__":
    unittest.main()
