"""Индекс SQL-объектов: схемы, таблицы, колонки, констрейнты, функции, вьюхи. Владелец: №1.

Разбор регулярками, а не парсером SQL: от индекса нужны имена, сигнатуры и номера строк, чтобы №2
знал схему и её контракты, а context.py мог понять, какой файл определяет упомянутый в коде объект.

До разбора текст маскируется: комментарии, строковые литералы и тела функций (`$tag$ ... $tag$`)
заменяются пробелами с сохранением переводов строк. Это даёт сразу три вещи: `CREATE`/`INSERT`
внутри тела функции не считаются объявлениями, скобка или запятая внутри литерала не ломают разбор
списка колонок, и номера строк остаются настоящими. Сами значения берутся из исходного текста.
"""
from __future__ import annotations

import re
from pathlib import Path

from harness.contracts import SqlObject

MAX_SCAN_BYTES = 1 << 20

IDENT = r'(?:"[^"]*"|[A-Za-z_][A-Za-z0-9_$]*)'
QUALNAME = rf"(?:{IDENT}\s*\.\s*)*{IDENT}"

SCHEMA = re.compile(rf"\bCREATE\s+SCHEMA\s+(?:IF\s+NOT\s+EXISTS\s+)?({QUALNAME})", re.IGNORECASE)
TABLE = re.compile(
    rf"\bCREATE\s+(?:(?:GLOBAL|LOCAL)\s+)?(?:(?:TEMP|TEMPORARY|UNLOGGED)\s+)?TABLE\s+"
    rf"(?:IF\s+NOT\s+EXISTS\s+)?({QUALNAME})\s*\(",
    re.IGNORECASE,
)
FUNCTION = re.compile(
    rf"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:PROCEDURE|FUNCTION)\s+({QUALNAME})\s*\(", re.IGNORECASE,
)
VIEW = re.compile(
    rf"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:MATERIALIZED\s+)?VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?({QUALNAME})",
    re.IGNORECASE,
)
INDEX = re.compile(
    rf"\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?"
    rf"({IDENT})\s+ON\s+({QUALNAME})\s*(?:USING\s+{IDENT}\s*)?\(",
    re.IGNORECASE,
)
RETURNS = re.compile(r"\bRETURNS\s+(.+?)(?=\bLANGUAGE\b|\bAS\b|\bSTABLE\b|\bVOLATILE\b|;|$)",
                     re.IGNORECASE | re.DOTALL)

# Слова, на которых заканчивается тип колонки и начинаются её ограничения.
COLUMN_TYPE_END = re.compile(
    r"\b(?:NOT|NULL|DEFAULT|CHECK|PRIMARY|UNIQUE|REFERENCES|GENERATED|CONSTRAINT|COLLATE|DEFERRABLE)\b",
    re.IGNORECASE,
)
INLINE_CHECK = re.compile(r"\bCHECK\s*\(", re.IGNORECASE)
NAMED_CONSTRAINT = re.compile(rf"\bCONSTRAINT\s+({IDENT})\s+(.*)", re.IGNORECASE | re.DOTALL)
TABLE_CONSTRAINT = re.compile(
    r"^\s*(?:CONSTRAINT\b|PRIMARY\s+KEY\b|FOREIGN\s+KEY\b|UNIQUE\b|CHECK\b|EXCLUDE\b|LIKE\b)",
    re.IGNORECASE,
)
DOLLAR_TAG = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$")
CONSTRAINT_KIND = (("PRIMARY KEY", "primary_key"), ("FOREIGN KEY", "foreign_key"),
                   ("UNIQUE", "unique"), ("CHECK", "check"), ("EXCLUDE", "exclude"))


def index_sql(repo: Path, paths: list[str]) -> list[SqlObject]:
    """Объекты файлов в том порядке, в каком переданы пути; внутри файла — в порядке объявления."""
    objects: list[SqlObject] = []
    for relative_path in paths:
        text = _read(repo, relative_path)
        if text is None:
            continue
        objects.extend(_index_file(relative_path, text))
    return objects


def _read(repo: Path, relative_path: str) -> str | None:
    if not relative_path.lower().endswith(".sql"):
        return None
    path = repo / relative_path
    try:
        if path.stat().st_size > MAX_SCAN_BYTES:
            return None
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _index_file(path: str, text: str) -> list[SqlObject]:
    masked = _mask(text)
    found: list[tuple[int, SqlObject]] = []

    for match in SCHEMA.finditer(masked):
        found.append((match.start(), _object(path, text, match.start(), "schema", _name(match, 1))))

    for match in TABLE.finditer(masked):
        qualname = _name(match, 1)
        body = _balanced(masked, match.end() - 1)
        columns, constraints = _table_body(text, masked, match.end(), body)
        found.append((match.start(), _object(path, text, match.start(), "table", qualname,
                                             ", ".join(columns))))
        for offset, name, signature in constraints:
            found.append((offset, _object(path, text, offset, "constraint", f"{qualname}.{name}",
                                          signature)))

    for match in FUNCTION.finditer(masked):
        end = _balanced(masked, match.end() - 1)
        args = _squeeze(text[match.end():end])
        tail = RETURNS.search(masked, end)
        returns = f" RETURNS {_squeeze(text[tail.start(1):tail.end(1)])}" if tail else ""
        found.append((match.start(), _object(path, text, match.start(), "function", _name(match, 1),
                                             f"({args}){returns}")))

    for match in VIEW.finditer(masked):
        found.append((match.start(), _object(path, text, match.start(), "view", _name(match, 1))))

    for match in INDEX.finditer(masked):
        table = _name(match, 2)
        schema = table.rpartition(".")[0]
        name = _name(match, 1)
        end = _balanced(masked, match.end() - 1)
        columns = _squeeze(text[match.end():end])
        found.append((match.start(), _object(path, text, match.start(), "index",
                                             f"{schema}.{name}" if schema else name,
                                             f"ON {table} ({columns})")))

    return [item for _, item in sorted(found, key=lambda pair: pair[0])]


def _object(path: str, text: str, offset: int, kind: str, qualname: str,
            signature: str | None = None) -> SqlObject:
    return SqlObject(path=path, kind=kind, qualname=qualname, signature=signature,
                     line=text.count("\n", 0, offset) + 1)


def _name(match: re.Match[str], group: int) -> str:
    return re.sub(r"\s*\.\s*", ".", match.group(group))


def _squeeze(fragment: str) -> str:
    return re.sub(r"\s+", " ", fragment).strip()


def _mask(text: str) -> str:
    """Комментарии, строковые литералы и тела `$tag$...$tag$` -> пробелы, переводы строк на месте."""
    chars = list(text)
    index = 0
    size = len(text)
    while index < size:
        rest = text[index:]
        if rest.startswith("--"):
            end = text.find("\n", index)
            end = size if end == -1 else end
        elif rest.startswith("/*"):
            end = _block_comment(text, index)
        elif rest.startswith("'"):
            end = _literal(text, index)
        elif (tag := DOLLAR_TAG.match(rest)) is not None:
            closing = text.find(tag.group(0), index + tag.end())
            end = size if closing == -1 else closing + tag.end()
        else:
            index += 1
            continue
        for position in range(index, end):
            if chars[position] != "\n":
                chars[position] = " "
        index = end
    return "".join(chars)


def _block_comment(text: str, start: int) -> int:
    depth = 0
    index = start
    while index < len(text):
        if text.startswith("/*", index):
            depth += 1
            index += 2
        elif text.startswith("*/", index):
            depth -= 1
            index += 2
            if depth == 0:
                return index
        else:
            index += 1
    return len(text)


def _literal(text: str, start: int) -> int:
    index = start + 1
    while index < len(text):
        if text[index] == "'":
            if text.startswith("''", index):
                index += 2
                continue
            return index + 1
        index += 1
    return len(text)


def _balanced(masked: str, open_paren: int) -> int:
    """Позиция закрывающей скобки для скобки в open_paren; конец текста, если баланс не сошёлся."""
    depth = 0
    for index in range(open_paren, len(masked)):
        if masked[index] == "(":
            depth += 1
        elif masked[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return len(masked)


def _split_items(masked: str, start: int, end: int) -> list[tuple[int, int]]:
    """Границы элементов списка, разделённых запятыми верхнего уровня."""
    items: list[tuple[int, int]] = []
    depth = 0
    item_start = start
    for index in range(start, end):
        char = masked[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            items.append((item_start, index))
            item_start = index + 1
    items.append((item_start, end))
    return items


def _table_body(text: str, masked: str, start: int,
                end: int) -> tuple[list[str], list[tuple[int, str, str]]]:
    """Колонки как 'имя тип' и ограничения как (смещение, имя, выражение)."""
    columns: list[str] = []
    constraints: list[tuple[int, str, str]] = []
    anonymous: dict[str, int] = {}
    for item_start, item_end in _split_items(masked, start, end):
        item = masked[item_start:item_end]
        if not item.strip():
            continue
        if TABLE_CONSTRAINT.match(item):
            offset = item_start + len(item) - len(item.lstrip())
            name, signature = _constraint(_squeeze(text[item_start:item_end]), anonymous)
            constraints.append((offset, name, signature))
            continue
        name = re.match(rf"\s*({IDENT})", item)
        if name is None:
            continue
        columns.append(_column(text, item, name))
        check = INLINE_CHECK.search(item)
        if check is not None:
            check_end = _balanced(masked, item_start + check.end() - 1)
            constraints.append((item_start + check.start(), f"{_name(name, 1)}_check",
                                _squeeze(text[item_start + check.start():check_end + 1])))
    return columns, constraints


def _column(text: str, item: str, name: re.Match[str]) -> str:
    stop = COLUMN_TYPE_END.search(item, name.end())
    column_type = _squeeze(item[name.end():stop.start() if stop else len(item)])
    return f"{_name(name, 1)} {column_type}".strip()


def _constraint(item: str, anonymous: dict[str, int]) -> tuple[str, str]:
    """Имя и выражение ограничения. Имя названного уходит в qualname, поэтому из выражения убирается."""
    named = NAMED_CONSTRAINT.match(item)
    if named is not None:
        return _name(named, 1), _squeeze(named.group(2))
    upper = item.upper()
    for prefix, label in CONSTRAINT_KIND:
        if upper.startswith(prefix):
            if label == "primary_key":
                return label, item
            anonymous[label] = anonymous.get(label, 0) + 1
            return f"{label}_{anonymous[label]}", item
    anonymous["constraint"] = anonymous.get("constraint", 0) + 1
    return f"constraint_{anonymous['constraint']}", item
