"""Чтение и валидация входного JSON. Владелец: №1 (перенесено с №4).

Правила (PROTOCOL.md, раздел 1):
  * все поля обязательны; protocol_version == "1.0";
  * относительные пути разрешаются от папки входного JSON;
  * repository существует и является папкой; output_dir НЕ существует;
  * case_id формата "команда/название"; difficulty и language — из Enum;
  * author.name и author.email — непустые строки; все limits > 0; seed — целое (не bool).
Ошибка -> InputError с понятным текстом (все найденные проблемы сразу, а не первая).

Неизвестные поля игнорируются: протокол требует наличия своих полей, но не запрещает чужие,
и расширение входа не должно ронять запуск.
"""
from __future__ import annotations

import json
import logging
import math
import os
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

from harness.contracts import PROTOCOL_VERSION, Author, CaseInput, Difficulty, Language, Limits

E = TypeVar("E", bound=Enum)

LOGGER = logging.getLogger(__name__)

INTEGER_LIMITS = (
    "agent_timeout_sec", "verifier_timeout_sec", "build_timeout_sec", "memory_mb", "storage_mb",
)
LIMIT_FIELDS = frozenset({*INTEGER_LIMITS, "cpus"})
AUTHOR_FIELDS = frozenset({"name", "email"})
INPUT_FIELDS = frozenset({
    "protocol_version", "repository", "brief", "output_dir", "case_id", "difficulty", "language",
    "source", "team", "author", "limits", "seed",
})

_JSON_KINDS: dict[type, str] = {
    bool: "логическое", int: "целое", float: "число", str: "строка", list: "массив", dict: "объект",
}


class InputError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def load_input(path: Path) -> CaseInput:
    """Разбирает входной JSON и возвращает CaseInput с абсолютными путями.

    Для №4 (pipeline/cli): при InputError result.json НЕ пишется — output_dir либо ещё не существует,
    либо принадлежит кому-то другому, и создавать его в этом случае нельзя. Текст ошибки
    (все проблемы сразу) выводится в stderr, код выхода — 2.
    """
    input_path = Path(os.path.abspath(path))
    data = _read_json(input_path)
    _warn_unknown(data, INPUT_FIELDS, "входной JSON")
    base = input_path.parent
    problems: list[str] = []

    protocol_version = _text(data, "protocol_version", problems)
    if protocol_version is not None and protocol_version != PROTOCOL_VERSION:
        problems.append(
            f'protocol_version: ожидается "{PROTOCOL_VERSION}", получено "{protocol_version}"'
        )

    repository = _path(data, "repository", base, problems)
    if repository is not None and not repository.is_dir():
        reason = "папки нет" if not repository.exists() else "это не папка"
        problems.append(f"repository: {reason}: {repository}")

    output_dir = _path(data, "output_dir", base, problems)
    if output_dir is not None and output_dir.exists():
        problems.append(f"output_dir: уже существует, перезапись запрещена: {output_dir}")
    if repository is not None and output_dir is not None and _is_inside(output_dir, repository):
        # Иначе результат окажется внутри исходника и сломает финальную сверку хэша снимка.
        problems.append(f"output_dir: не должен лежать внутри repository: {output_dir}")

    brief = _text(data, "brief", problems, required_nonempty=True)
    case_id = _case_id(data, problems)
    difficulty = _enum(data, "difficulty", Difficulty, problems)
    language = _enum(data, "language", Language, problems)
    source = _text(data, "source", problems, required_nonempty=True)
    team = _text(data, "team", problems, required_nonempty=True)
    author = _author(data, problems)
    limits = _limits(data, problems)
    seed = _integer(data, "seed", problems, label="seed", positive=False)

    if problems:
        raise InputError(problems)

    assert repository is not None and output_dir is not None and brief is not None
    assert case_id is not None and difficulty is not None and language is not None
    assert source is not None and team is not None and author is not None
    assert limits is not None and seed is not None and protocol_version is not None
    return CaseInput(
        protocol_version=protocol_version,
        repository=repository,
        brief=brief,
        output_dir=output_dir,
        case_id=case_id,
        difficulty=difficulty,
        language=language,
        source=source,
        team=team,
        author=author,
        limits=limits,
        seed=seed,
        input_path=input_path,
    )


# ---------------------------------------------------------------------------
# Файл целиком: тут собирать нечего, поэтому одна понятная проблема
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise InputError([f"входного файла нет: {path}"])
    if not path.is_file():
        raise InputError([f"вход должен быть файлом: {path}"])
    try:
        text = path.read_text(encoding="utf-8-sig")  # utf-8-sig: BOM от Windows-редакторов
    except UnicodeDecodeError as exc:
        raise InputError([f"входной файл не в UTF-8: {exc}"]) from exc
    except OSError as exc:
        raise InputError([f"входной файл не читается: {exc}"]) from exc
    try:
        data = json.loads(text, parse_constant=_reject_constant)
    except ValueError as exc:  # JSONDecodeError и отказ на NaN/Infinity
        raise InputError([f"входной файл не разбирается как JSON: {exc}"]) from exc
    if not isinstance(data, dict):
        raise InputError([f"входной JSON должен быть объектом, получен {_kind(data)}"])
    return data


def _reject_constant(name: str) -> Any:
    """NaN, Infinity и -Infinity json.loads принимает по умолчанию, но это не JSON
    и не осмысленные лимиты или seed."""
    raise ValueError(f"{name} недопустим во входном JSON")


# ---------------------------------------------------------------------------
# Поля: каждая проверка добавляет проблемы в общий список и возвращает None при неудаче
# ---------------------------------------------------------------------------

def _text(
    data: dict[str, Any], key: str, problems: list[str], *,
    label: str | None = None, required_nonempty: bool = False,
) -> str | None:
    label = label or key
    if key not in data:
        problems.append(f"{label}: поле обязательно")
        return None
    value = data[key]
    if not isinstance(value, str):
        problems.append(f"{label}: ожидается строка, получено {_kind(value)}")
        return None
    if required_nonempty and not value.strip():
        problems.append(f"{label}: строка не должна быть пустой")
        return None
    return value


def _path(data: dict[str, Any], key: str, base: Path, problems: list[str]) -> Path | None:
    value = _text(data, key, problems, required_nonempty=True)
    if value is None:
        return None
    # Относительные пути — от папки входного JSON, а не от cwd (PROTOCOL.md, раздел 1).
    return Path(os.path.normpath(value if os.path.isabs(value) else base / value))


def _enum(data: dict[str, Any], key: str, enum_type: type[E], problems: list[str]) -> E | None:
    value = _text(data, key, problems)
    if value is None:
        return None
    try:
        return enum_type(value)
    except ValueError:
        allowed = ", ".join(member.value for member in enum_type)
        problems.append(f'{key}: ожидается одно из ({allowed}), получено "{value}"')
        return None


def _case_id(data: dict[str, Any], problems: list[str]) -> str | None:
    value = _text(data, "case_id", problems, required_nonempty=True)
    if value is None:
        return None
    problem = _case_id_problem(value)
    if problem is not None:
        problems.append(f'case_id: {problem}; ожидается "команда/название", получено "{value}"')
        return None
    return value


def _case_id_problem(value: str) -> str | None:
    """Сам идентификатор остаётся как есть, юникод разрешён: приводить его к имени файла
    или к тегу Docker-образа — забота того модуля, где это нужно."""
    if value.count("/") != 1:
        return "нужен ровно один «/»"
    if "\\" in value:
        return "обратный слеш недопустим"
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return "управляющие символы недопустимы"
    for part in value.split("/"):
        if not part:
            return "обе части должны быть непустыми"
        if part != part.strip():
            return "части не должны начинаться или заканчиваться пробелом"
        if part in (".", ".."):
            return "часть не может быть «.» или «..»"
    return None


def _author(data: dict[str, Any], problems: list[str]) -> Author | None:
    if "author" not in data:
        problems.append("author: поле обязательно")
        return None
    value = data["author"]
    if not isinstance(value, dict):
        problems.append(f"author: ожидается объект, получено {_kind(value)}")
        return None
    _warn_unknown(value, AUTHOR_FIELDS, "author")
    name = _text(value, "name", problems, label="author.name", required_nonempty=True)
    email = _text(value, "email", problems, label="author.email", required_nonempty=True)
    if name is None or email is None:
        return None
    return Author(name=name, email=email)


def _limits(data: dict[str, Any], problems: list[str]) -> Limits | None:
    if "limits" not in data:
        problems.append("limits: поле обязательно")
        return None
    value = data["limits"]
    if not isinstance(value, dict):
        problems.append(f"limits: ожидается объект, получено {_kind(value)}")
        return None
    _warn_unknown(value, LIMIT_FIELDS, "limits")
    numbers = {
        name: _integer(value, name, problems, label=f"limits.{name}", positive=True)
        for name in INTEGER_LIMITS
    }
    cpus = _number(value, "cpus", problems, label="limits.cpus")
    if cpus is None or any(number is None for number in numbers.values()):
        return None
    return Limits(cpus=cpus, **numbers)  # type: ignore[arg-type]


def _integer(
    data: dict[str, Any], key: str, problems: list[str], *, label: str, positive: bool,
) -> int | None:
    if key not in data:
        problems.append(f"{label}: поле обязательно")
        return None
    value = data[key]
    # isinstance(True, int) истинно, поэтому bool отсекается отдельно.
    if isinstance(value, bool) or not isinstance(value, int):
        problems.append(f"{label}: ожидается целое число, получено {_kind(value)}")
        return None
    if positive and value <= 0:
        problems.append(f"{label}: должно быть больше нуля, получено {value}")
        return None
    return value


def _number(data: dict[str, Any], key: str, problems: list[str], *, label: str) -> float | None:
    if key not in data:
        problems.append(f"{label}: поле обязательно")
        return None
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        problems.append(f"{label}: ожидается число, получено {_kind(value)}")
        return None
    if not math.isfinite(value):
        # NaN и Infinity отсекает parse_constant, но 1e400 json.loads тихо превращает в inf.
        problems.append(f"{label}: ожидается конечное число, получено {value}")
        return None
    if value <= 0:
        problems.append(f"{label}: должно быть больше нуля, получено {value}")
        return None
    return float(value)


def _is_inside(path: Path, parent: Path) -> bool:
    """Сравнение после normpath и normcase: на Windows регистр и разделители не должны решать."""
    target = os.path.normcase(os.path.normpath(path))
    root = os.path.normcase(os.path.normpath(parent))
    return target == root or target.startswith(os.path.join(root, ""))


def _warn_unknown(data: dict[str, Any], known: frozenset[str], where: str) -> None:
    """Незнакомые поля не ошибка (протокол их не запрещает), но молчать о них не стоит:
    так видно опечатку в имени поля и расширение протокола организаторами."""
    unknown = sorted(set(data) - known)
    if unknown:
        LOGGER.warning("%s: незнакомые поля игнорируются: %s", where, ", ".join(unknown))


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    return _JSON_KINDS.get(type(value), type(value).__name__)
