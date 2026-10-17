"""Извлечение текста из присланного TXT или DOCX без запуска их содержимого."""

from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET


MAX_FILE_BYTES = 2 * 1024 * 1024


def extract_text(filename, content):
    if len(content) > MAX_FILE_BYTES:
        raise ValueError("Размер файла должен быть не более 2 МБ.")
    suffix = Path(filename).suffix.lower()
    if suffix == ".txt":
        try:
            text = content.decode("utf-8-sig")
        except UnicodeError as error:
            raise ValueError("Сохраните TXT в кодировке UTF-8.") from error
    elif suffix == ".docx":
        try:
            with ZipFile(BytesIO(content)) as archive:
                info = archive.getinfo("word/document.xml")
                if info.file_size > MAX_FILE_BYTES:
                    raise ValueError("Текст внутри DOCX слишком большой.")
                xml = archive.read(info)
                if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
                    raise ValueError("Неподдерживаемая структура DOCX.")
                root = ET.fromstring(xml)
            namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            paragraphs = []
            for paragraph in root.findall(".//w:p", namespace):
                parts = []
                for element in paragraph.iter():
                    if element.tag == "{" + namespace["w"] + "}t":
                        parts.append(element.text or "")
                    elif element.tag.endswith("}tab"):
                        parts.append("\t")
                    elif element.tag.endswith("}br"):
                        parts.append("\n")
                paragraphs.append("".join(parts))
            text = "\n".join(paragraphs)
        except (BadZipFile, KeyError, ET.ParseError, RuntimeError) as error:
            raise ValueError("Не удалось прочитать DOCX. Проверьте файл.") from error
    else:
        raise ValueError("Поддерживаются текст сообщения, TXT и DOCX.")
    if not text.strip():
        raise ValueError("В файле нет текста. Изображения и сканы не распознаются.")
    return text.strip()
