"""Разбор ответов LLM (JSON и файлы в fenced-блоках), с понятными ошибками для повтора. Владелец: №2."""
from __future__ import annotations

import json
import re


class ParsingError(ValueError):
    """Ошибка разбора ответа от LLM."""


def extract_json(text: str) -> object:
    """Извлекает и парсит JSON из ответа LLM.

    Поддерживает:
    1. Чистый JSON.
    2. JSON, обернутый в markdown-блоки ```json ... ``` или ``` ... ```.
    3. JSON, окруженный пояснительным текстом до и после.
    4. Автоматическую очистку от висячих запятых перед } и ].
    """
    text = text.strip()
    if not text:
        raise ParsingError("Empty response from LLM; cannot extract JSON")

    # 1. Попытка распарсить текст напрямую
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Поиск блоков ```json ... ``` или ``` ... ```
    fenced_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    for block in fenced_blocks:
        candidate = block.strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # Попытка очистить от висячих запятых: ,} -> } и ,] -> ]
            cleaned = re.sub(r",\s*([\]}])", r"\1", candidate)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                continue

    # 3. Поиск первого { ... } или [ ... ]
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate = text[first_brace : last_brace + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            cleaned = re.sub(r",\s*([\]}])", r"\1", candidate)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass

    first_bracket = text.find("[")
    last_bracket = text.rfind("]")
    if first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
        candidate = text[first_bracket : last_bracket + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            cleaned = re.sub(r",\s*([\]}])", r"\1", candidate)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass

    preview = text[:300] + ("..." if len(text) > 300 else "")
    raise ParsingError(f"Could not extract valid JSON from LLM response:\n{preview}")


def extract_files(text: str, default_filename: str | None = None) -> dict[str, str]:
    """Извлекает словарь файлов {имя_файла: содержимое} из ответа LLM.

    Поддерживает форматы:
    1. JSON-словарь вида {"filename": "content"}.
    2. Markdown-заголовки с именами файлов перед кодовыми блоками:
       ### File: test_example.py
       ```python
       def test_...
       ```
    3. Имена файлов с обратными кавычками или жирным шрифтом:
       **`test_example.py`**:
       ```python
       ...
       ```
    4. Комментарии с именем файла в первой строке блока:
       ```python
       # test_example.py
       ...
       ```
    5. Если имя файла не найдено, но передан default_filename и найден ровно один блок,
       использует default_filename.
    """
    text = text.strip()
    if not text:
        raise ParsingError("Empty response from LLM; cannot extract files")

    # 1. Проверяем, не является ли ответ JSON-словарем
    try:
        obj = extract_json(text)
        if isinstance(obj, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in obj.items()):
            return {_clean_path(k): v for k, v in obj.items()}
    except ParsingError:
        pass

    files: dict[str, str] = {}

    # 2. Паттерн: Заголовок с именем файла перед блоком кода
    # Пример: ### File: tests/test_settlement.py \n ```python \n ... \n ```
    pattern_header = re.compile(
        r"(?:^|\n)(?:#{1,6}\s*(?:File:?)?|\*\*(?:File:?)?|File:?)\s*[`\"]?([a-zA-Z0-9_\-./\\]+\.[a-zA-Z0-9_]+)[`\"]?\s*(?::|\*\*)?\s*\n+```[a-zA-Z0-9_\-]*\n([\s\S]*?)\n```",
        re.MULTILINE | re.IGNORECASE,
    )
    for match in pattern_header.finditer(text):
        filename = _clean_path(match.group(1))
        content = match.group(2)
        files[filename] = content

    if files:
        return files

    # 3. Паттерн: имя файла внутри первой строки блока кода:
    # ```python
    # # tests/test_settlement.py
    # ...
    # ```
    pattern_inline_comment = re.compile(
        r"```[a-zA-Z0-9_\-]*\n\s*(?:#|//|<!--)\s*[`\"]?([a-zA-Z0-9_\-./\\]+\.[a-zA-Z0-9_]+)[`\"]?\s*(?:-->)?\n([\s\S]*?)\n```",
        re.MULTILINE,
    )
    for match in pattern_inline_comment.finditer(text):
        filename = _clean_path(match.group(1))
        content = match.group(2)
        files[filename] = content

    if files:
        return files

    # 4. Паттерн: одиночный кодовый блок с default_filename
    if default_filename is not None:
        single_block = re.findall(r"```[a-zA-Z0-9_\-]*\n([\s\S]*?)\n```", text)
        if len(single_block) == 1:
            return {_clean_path(default_filename): single_block[0]}
        elif not single_block and text:
            # Если нет блоков вовсе, но есть текст и нужен default_filename
            return {_clean_path(default_filename): text}

    preview = text[:300] + ("..." if len(text) > 300 else "")
    raise ParsingError(f"Could not extract files from LLM response:\n{preview}")


def extract_code_block(text: str, default: str = "") -> str:
    """Извлекает содержимое первого блока кода или возвращает очищенный текст, если блоков нет."""
    text = text.strip()
    if not text:
        return default

    blocks = re.findall(r"```[a-zA-Z0-9_\-]*\n([\s\S]*?)\n```", text)
    if blocks:
        return blocks[0].strip()

    return text


def extract_patch(text: str) -> str:
    """Извлекает unified diff (патч) из ответа LLM."""
    text = text.strip()
    # Сначала ищем в кодовом блоке
    blocks = re.findall(r"```(?:diff|patch)?\n([\s\S]*?)\n```", text, re.IGNORECASE)
    for block in blocks:
        if "--- " in block and "+++ " in block:
            return block.strip() + "\n"

    # Ищем напрямую по маркерам diff
    pos = text.find("--- ")
    if pos != -1 and "+++ " in text[pos:]:
        # Ищем конец патча или конец текста
        diff_text = text[pos:]
        end_match = re.search(r"\n(?=[^\s@+\-\\ ])", diff_text)
        if end_match:
            diff_text = diff_text[: end_match.start()]
        return diff_text.strip() + "\n"

    preview = text[:300] + ("..." if len(text) > 300 else "")
    raise ParsingError(f"Could not extract unified diff patch from LLM response:\n{preview}")


def _clean_path(path_str: str) -> str:
    """Очищает путь к файлу от лишних кавычек, пробелов и ведущих слешей."""
    path = path_str.strip().strip("'\"`").replace("\\", "/")
    path = re.sub(r"^\.?/+", "", path)
    return path
