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


def _exception_type_from_message(message: str | None) -> str:
    """Тип исключения из первой строки сообщения junit.

    pytest пишет <failure> без атрибута type и для голого assert, и для любого другого
    исключения в теле теста, поэтому различить их можно только по сообщению:
    'assert 1 == 2' против 'TypeError: unsupported operand type(s)'.
    Без этого fail_to_pass, падающий на TypeError или AttributeError, засчитывался бы
    как воспроизведённый дефект (PROTOCOL §5.4).

    Префикс считается типом исключения, только если похож на его имя, — чтобы не принять
    за тип начало обычного сообщения assert.
    """
    if not message:
        return "AssertionError"
    match = EXCEPTION_PREFIX.match(message)
    return match.group(1) if match else "AssertionError"


def _exception_type_from_error(message: str | None, text: str | None) -> str | None:
    """Тип исключения для <error>: ошибка сбора, импорта или фикстуры.

    pytest не пишет атрибут type ни у <failure>, ни у <error> — только у <skipped>
    (см. _pytest/junitxml.py). У ошибки сбора message всегда буквально 'collection failure',
    а само исключение лежит последней строкой трейсбека в теле элемента и помечено 'E ':

        E     File ".../repo/module.py", line 1
        E   SyntaxError: invalid syntax

    Поэтому сообщение разбирается как у failure, а если в нём типа нет — берётся последнее
    похожее на имя исключения совпадение из трейсбека (последнее, потому что при цепочке
    исключений внизу стоит то, которое дошло до pytest).

    В отличие от _exception_type_from_message, умолчания 'AssertionError' здесь нет:
    ошибка сбора никогда не является провалом проверки, и выдавать её за assert нельзя.
    """
    if message:
        match = EXCEPTION_PREFIX.match(message)
        if match:
            return match.group(1)

    if not text:
        return None

    found: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        # Строки трейсбека pytest помечает 'E' с отступом; убираем маркер, если он есть.
        if line.startswith("E ") or line == "E":
            line = line[1:].strip()
        match = EXCEPTION_PREFIX.match(line)
        if match:
            found = match.group(1)
    return found


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
                exception_type=exc_type or _exception_type_from_message(msg),
            )
        elif error_el is not None:
            msg = error_el.get("message")
            exc_type = error_el.get("type")
            if not msg and error_el.text:
                msg = error_el.text.strip().splitlines()[0] if error_el.text.strip() else None
            reports[test_id] = TestReport(
                outcome=TestOutcome.ERROR,
                message=msg,
                exception_type=exc_type or _exception_type_from_error(msg, error_el.text),
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

