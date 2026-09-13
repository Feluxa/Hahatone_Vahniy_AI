from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree

from harness.contracts import TestOutcome, TestReport
from harness.pytest_ids import canonical_test_id

# Имя исключения в начале сообщения: 'TypeError: ...', 'pytest.PytestUnraisableWarning: ...'.
# Хвост имени ограничен, чтобы 'assert foo: bar' не был принят за тип исключения.
EXCEPTION_PREFIX = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Exit|Interrupt|Failed|Warning))\s*:"
)

# Последняя строка трейсбека pytest: '<файл>:<строка>: <ИмяИсключения>'. Имя здесь не
# квалифицировано модулем и есть даже у голого assert, которому pytest не печатает тип.
CRASH_LINE = re.compile(r"^.*:\d+:\s*([A-Za-z_][A-Za-z0-9_.]*)\s*$")


def _normalize_test_id(file_attr: str | None, classname_attr: str | None, name_attr: str) -> str:
    """Нормализует путь и имя теста к формату pytest ID, например 'tests/test_x.py::test_name'."""
    path = ""
    if file_attr:
        path = file_attr.replace("\\", "/")
        # Срезаем префиксы корня и окружения
        for prefix in ("/app/repo/", "app/repo/", "/tests/", "tests/"):
            if path.startswith(prefix):
                path = path[len(prefix):]
                break
        path = path.lstrip("/")
        if not path.startswith("tests/"):
            path = f"tests/{path}"
    elif classname_attr:
        # Пытаемся восстановить файл из classname
        parts = classname_attr.split(".")
        path = "/".join(parts) + ".py"
        if not path.startswith("tests/"):
            path = "tests/" + path.lstrip("/")

    # Определяем наличие класса внутри файла
    class_name = ""
    if classname_attr and file_attr:
        file_stem = Path(file_attr).stem
        parts = classname_attr.split(".")
        if file_stem in parts:
            idx = parts.index(file_stem)
            subparts = parts[idx + 1:]
            if subparts:
                class_name = "::".join(subparts)

    if class_name:
        return f"{path}::{class_name}::{name_attr}"
    return f"{path}::{name_attr}"


def _exception_type_from_report(message: str | None, text: str | None) -> str | None:
    """Тип исключения по отчёту pytest. None — определить не удалось.

    pytest не пишет атрибут type ни у <failure>, ни у <error> — только у <skipped>
    (см. _pytest/junitxml.py), поэтому тип восстанавливается из текста. Источники, в
    порядке надёжности:

    1. Последняя строка трейсбека — место падения и имя исключения:
       '/tests/test_case.py:45: AssertionError'. Имя там есть всегда и в чистом виде;
       у голого 'assert a == b' его больше нет нигде.
    2. Строки трейсбека с маркером 'E' — так выглядит ошибка сбора, у которой строки
       места падения нет: 'E   SyntaxError: invalid syntax'. Берётся последнее
       совпадение: при цепочке исключений внизу стоит дошедшее до pytest.
    3. Начало message: 'TypeError: ...'. В message имя бывает квалифицировано модулем
       ('test_kinds.CheckViolation: ...'), поэтому источник запасной.
    4. message вида 'assert ...' — голый assert при отключённом трейсбеке.

    Умолчания нет намеренно. Прежнее «всё непонятное — это AssertionError» засчитывало
    падение по любой неопознанной причине как воспроизведённый дефект, что запрещает
    PROTOCOL §5.4. Неопознанный тип должен оставаться неопознанным: failed_by_assertion
    у такого отчёта False, и вердикт потребует разобраться.
    """
    lines = [line.rstrip() for line in (text or "").splitlines() if line.strip()]

    if lines:
        crash = CRASH_LINE.match(lines[-1])
        if crash:
            return crash.group(1)

    found: str | None = None
    for line in lines:
        stripped = line.strip()
        # Строки трейсбека pytest помечает 'E' с отступом; убираем маркер, если он есть.
        if stripped.startswith("E ") or stripped == "E":
            stripped = stripped[1:].strip()
        match = EXCEPTION_PREFIX.match(stripped)
        if match:
            found = match.group(1)
    if found:
        return found

    if message:
        match = EXCEPTION_PREFIX.match(message)
        if match:
            return match.group(1)
        if message.lstrip().startswith("assert"):
            return "AssertionError"

    return None


def parse_junit(xml_path: Path) -> dict[str, TestReport]:
    """Разбирает JUnit XML от pytest в словарь test_id -> TestReport."""
    if not xml_path.exists():
        return {}

    try:
        content = xml_path.read_text(encoding="utf-8")
        if not content.strip():
            return {}
        root = ElementTree.fromstring(content)
    except Exception:
        return {}

    reports: dict[str, TestReport] = {}
    for case in root.findall(".//testcase"):
        name = case.get("name", "")
        classname = case.get("classname", "")
        file_attr = case.get("file")

        # Канон тот же, что у списков в task.toml и у прогона collect: иначе
        # один и тот же тест выглядит как два разных при сверке.
        test_id = canonical_test_id(_normalize_test_id(file_attr, classname, name))

        failure_el = case.find("failure")
        error_el = case.find("error")
        skipped_el = case.find("skipped")

        if failure_el is not None:
            msg = failure_el.get("message")
            exc_type = failure_el.get("type")
            if not msg and failure_el.text:
                msg = failure_el.text.strip().splitlines()[0] if failure_el.text.strip() else None
            reports[test_id] = TestReport(
                outcome=TestOutcome.FAILED,
                message=msg,
                exception_type=exc_type or _exception_type_from_report(msg, failure_el.text),
            )
        elif error_el is not None:
            msg = error_el.get("message")
            exc_type = error_el.get("type")
            if not msg and error_el.text:
                msg = error_el.text.strip().splitlines()[0] if error_el.text.strip() else None
            reports[test_id] = TestReport(
                outcome=TestOutcome.ERROR,
                message=msg,
                exception_type=exc_type or _exception_type_from_report(msg, error_el.text),
            )
        elif skipped_el is not None:
            msg = skipped_el.get("message")
            reports[test_id] = TestReport(
                outcome=TestOutcome.SKIPPED,
                message=msg,
                exception_type=None,
            )
        else:
            reports[test_id] = TestReport(
                outcome=TestOutcome.PASSED,
                message=None,
                exception_type=None,
            )

    return reports


def with_missing(reports: dict[str, TestReport], expected_ids: list[str]) -> dict[str, TestReport]:
    """Добавляет TestOutcome.MISSING для ожидаемых, но не найденных ID."""
    result = dict(reports)
    for expected_id in expected_ids:
        if expected_id not in result:
            result[expected_id] = TestReport(
                outcome=TestOutcome.MISSING,
                message=f"Test '{expected_id}' was expected but not found in reports",
            )
    return result

