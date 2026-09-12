"""Генерация task/task.toml. Владелец: №1 (перенесено с №4).

Образец: hackathon-participants/example-case/task.toml.
schema_version = "1.1"; [task] name=case_id, description, authors; [metadata] task_type="agentic",
bank_domain, language, build_tool="docker", difficulty, source, team, fail_to_pass, pass_to_pass, anti_cheat;
[agent] timeout_sec; [verifier] timeout_sec; [environment] allow_internet=false, build_timeout_sec, cpus,
memory_mb, storage_mb. Лимиты и автор — из входа.

Манифест пишется своим рендером, а не библиотекой: формат образца (отступ в массивах, висящая
запятая, inline-таблица авторов) — часть внешнего контракта, и повторить его надёжнее прямо.
Экранирование при этом честное: в описании и имени автора бывают кавычки, обратные слеши и
управляющие символы, а порченый TOML ломает приёмку кейса целиком.

Списки тестов проверяются одинаково на запись и на чтение: пустой fail_to_pass, идентификатор
без "::" и один и тот же ID в двух списках — это ошибка манифеста, а не задача верификатора.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from harness.contracts import TASK_SCHEMA_VERSION, CaseInput, CaseSpec, TestLists

TASK_TYPE = "agentic"
BUILD_TOOL = "docker"
TEST_ID_SEPARATOR = "::"
LIST_NAMES: tuple[str, ...] = ("fail_to_pass", "pass_to_pass", "anti_cheat")

ARRAY_INDENT = "    "

# Обязательные по TOML: всё остальное из диапазона управляющих символов уходит в \uXXXX.
ESCAPES: dict[str, str] = {
    "\\": "\\\\", '"': '\\"', "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r",
}


class ManifestError(ValueError):
    """Манифест собрать или прочитать нельзя. Несёт все найденные проблемы сразу."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def render_task_toml(case: CaseInput, spec: CaseSpec, lists: TestLists) -> str:
    _check(lists)
    limits = case.limits
    blocks = [
        f"schema_version = {_string(TASK_SCHEMA_VERSION)}",
        "\n".join([
            "[task]",
            f"name = {_string(case.case_id)}",
            f"description = {_string(spec.description)}",
            f"authors = [{{ name = {_string(case.author.name)},"
            f" email = {_string(case.author.email)} }}]",
        ]),
        "\n".join([
            "[metadata]",
            f"task_type = {_string(TASK_TYPE)}",
            f"bank_domain = {_string(spec.bank_domain)}",
            f"language = {_string(case.language.value)}",
            f"build_tool = {_string(BUILD_TOOL)}",
            f"difficulty = {_string(case.difficulty.value)}",
            f"source = {_string(case.source)}",
            f"team = {_string(case.team)}",
            _array("fail_to_pass", lists.fail_to_pass),
            _array("pass_to_pass", lists.pass_to_pass),
            _array("anti_cheat", lists.anti_cheat),
        ]),
        f"[agent]\ntimeout_sec = {limits.agent_timeout_sec}",
        f"[verifier]\ntimeout_sec = {limits.verifier_timeout_sec}",
        "\n".join([
            "[environment]",
            "allow_internet = false",
            f"build_timeout_sec = {limits.build_timeout_sec}",
            f"cpus = {_number(limits.cpus)}",
            f"memory_mb = {limits.memory_mb}",
            f"storage_mb = {limits.storage_mb}",
        ]),
    ]
    return "\n\n".join(blocks) + "\n"


def read_test_lists(task_toml: Path) -> TestLists:
    """Обратная операция: списки тестов из готового task.toml (нужна №3 для прогонов)."""
    try:
        data = tomllib.loads(task_toml.read_text(encoding="utf-8"))
    except OSError as error:
        raise ManifestError([f"{task_toml}: файл не читается: {error}"]) from error
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ManifestError([f"{task_toml}: не разбирается как TOML: {error}"]) from error

    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        raise ManifestError([f"{task_toml}: нет секции [metadata]"])

    problems: list[str] = []
    values: dict[str, list[str]] = {}
    for name in LIST_NAMES:
        raw = metadata.get(name)
        if raw is None:
            problems.append(f"{name}: поле обязательно")
        elif not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
            problems.append(f"{name}: ожидается массив строк")
        else:
            values[name] = raw
    if problems:
        raise ManifestError(problems)

    lists = TestLists(**values)
    _check(lists)
    return lists


def _check(lists: TestLists) -> None:
    problems: list[str] = []
    if not lists.fail_to_pass:
        problems.append("fail_to_pass: список пуст, кейс без воспроизводимого дефекта не собирается")
    for name in LIST_NAMES:
        for test_id in getattr(lists, name):
            if not test_id.strip():
                problems.append(f"{name}: пустой идентификатор теста")
            elif TEST_ID_SEPARATOR not in test_id:
                problems.append(
                    f'{name}: идентификатор без "{TEST_ID_SEPARATOR}": {test_id}'
                )
    for test_id in lists.duplicates():
        problems.append(f"идентификатор встречается больше одного раза: {test_id}")
    if problems:
        raise ManifestError(problems)


def _string(value: str) -> str:
    escaped = []
    for char in value:
        if char in ESCAPES:
            escaped.append(ESCAPES[char])
        elif char < " " or char == "\x7f":
            escaped.append(f"\\u{ord(char):04X}")
        else:
            escaped.append(char)
    return '"' + "".join(escaped) + '"'


def _number(value: float) -> str:
    """Целое значение остаётся целым: в образце `cpus = 1`, а не `cpus = 1.0`."""
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def _array(name: str, values: list[str]) -> str:
    if not values:
        return f"{name} = []"
    items = "\n".join(f"{ARRAY_INDENT}{_string(value)}," for value in values)
    return f"{name} = [\n{items}\n]"
