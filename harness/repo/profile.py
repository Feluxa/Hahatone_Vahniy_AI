"""Определение профиля запуска проекта. Владелец: №1.

Источники: pyproject.toml ([tool.pytest.ini_options]), requirements.lock / requirements.txt,
alembic.ini, README. Для meridian ожидается: python 3.11, requirements.lock, pythonpath backend/src,
PostgreSQL 16, миграция `python -m alembic upgrade head`, сид sql/090_core_seed.sql.

Профиль — эвристика, а не контракт, поэтому неполнота источников не обрывает прогон: ProfileError
только на структурных проблемах (нет папки, не папка, битый pyproject.toml), всё остальное
деградирует до None, пустых списков и DEFAULT_PYTHON_VERSION.

Недоверенные файлы (repo/trust.py) из всех просмотров исключены: postgres_major и env_vars уезжают
в Dockerfile, и импортированный тикет не должен решать, какая версия PostgreSQL окажется в образе.
Значения переменных окружения не читаются никогда — только имена.
"""
from __future__ import annotations

import configparser
import logging
import re
import tomllib
from pathlib import Path

from harness.contracts import RunProfile
from harness.repo.snapshot import SnapshotError, list_regular_files
from harness.repo.trust import find_untrusted

LOGGER = logging.getLogger(__name__)

DEFAULT_PYTHON_VERSION = "3.11"
MAX_SCAN_BYTES = 256 * 1024

# Файлы, где проект описывает своё окружение: документация, compose, образы, CI, ini-конфиги.
DOC_SUFFIXES: frozenset[str] = frozenset({".md", ".rst", ".txt"})
CONFIG_SUFFIXES: frozenset[str] = frozenset({".ini", ".cfg"})

PIP_REQUIREMENTS_NAMES: tuple[str, ...] = ("requirements.lock", "requirements.txt")
NON_PIP_LOCK_NAMES: frozenset[str] = frozenset({"poetry.lock", "uv.lock", "pipfile.lock", "pdm.lock"})

POSTGRES_DRIVERS: frozenset[str] = frozenset({
    "psycopg", "psycopg-binary", "psycopg2", "psycopg2-binary", "asyncpg", "aiopg", "pg8000",
})

# Переменные окружения самой оболочки: к профилю проекта отношения не имеют.
SHELL_ENV_VARS: frozenset[str] = frozenset({
    "PATH", "HOME", "PWD", "OLDPWD", "USER", "LOGNAME", "SHELL", "SHLVL", "TERM", "LANG",
    "LC_ALL", "TMPDIR", "TMP", "TEMP", "HOSTNAME", "IFS", "PS1", "EDITOR", "CI",
})

SEED_TOKENS: frozenset[str] = frozenset({"seed", "seeds", "fixture", "fixtures"})
TEST_DIR_NAMES: frozenset[str] = frozenset({"test", "tests"})

PYTHON_SPECIFIER = re.compile(r"(?:>=|~=|==)\s*(\d+)\.(\d+)")
RUFF_TARGET = re.compile(r"^py(\d)(\d+)$")
PLAIN_VERSION = re.compile(r"(\d+)\.(\d+)")
# 'postgresql+psycopg://' не матчится: '+' не входит в разделители, значит версия оттуда не возьмётся.
POSTGRES_VERSION = re.compile(r"postgres(?:ql)?[\s:_v-]{0,3}(\d{1,2})(?!\d)", re.IGNORECASE)
POSTGRES_MENTION = re.compile(r"\b(?:postgres\w*|psql)\b", re.IGNORECASE)
ENV_IN_CODE = re.compile(
    r"os\.environ\[\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']"
    r"|os\.(?:getenv|environ\.get)\(\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']"
)
ENV_IN_SHELL = re.compile(r"\$\{?([A-Z][A-Z0-9_]{2,})\}?")
ENV_IN_DOTENV = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
PSQL_FILE = re.compile(r"psql[^\n]*?-f\s+([A-Za-z0-9_.\-/]+\.sql)")
PIP_REQUIREMENT_LINE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[^\]]+\])?\s*(?:[=<>!~@].*)?$")
DEPENDENCY_NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


class ProfileError(ValueError):
    """Профиль определить нельзя: нет папки, это не папка, или pyproject.toml не читается."""


def detect_run_profile(repo: Path) -> RunProfile:
    if not repo.exists():
        raise ProfileError(f"репозитория нет: {repo}")
    if not repo.is_dir():
        raise ProfileError(f"путь к репозиторию не папка: {repo}")

    paths = _trusted_paths(repo)
    pyproject = _load_pyproject(repo)
    pytest_config = _load_pytest_config(repo, pyproject)
    testpaths = _as_list(pytest_config.get("testpaths"))
    documents = _read_documents(repo, paths)
    dependency_names, requirements_file = _load_dependencies(repo, paths, pyproject)

    return RunProfile(
        python_version=_detect_python_version(repo, paths, pyproject),
        requirements_file=requirements_file,
        pytest_pythonpath=_as_list(pytest_config.get("pythonpath")),
        pytest_testpaths=testpaths,
        needs_postgres=_detect_needs_postgres(dependency_names, pytest_config, documents),
        postgres_major=_detect_postgres_major(documents),
        migration_command=_detect_migration_command(paths),
        seed_sql_files=_detect_seed_sql(paths, testpaths, documents),
        env_vars=_detect_env_vars(repo, paths, documents),
    )


def _trusted_paths(repo: Path) -> list[str]:
    """Все обычные файлы, кроме недоверенных: инъекция не должна влиять на сборку образа."""
    try:
        paths = list_regular_files(repo)
    except SnapshotError as exc:
        raise ProfileError(str(exc)) from exc
    untrusted = set(find_untrusted(repo))
    return [path for path in paths if path not in untrusted]


# --- источники ---------------------------------------------------------------------------------

def _load_pyproject(repo: Path) -> dict[str, object]:
    text = _read_text(repo / "pyproject.toml")
    if text is None:
        return {}
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"pyproject.toml не разбирается как TOML: {exc}") from exc


def _load_pytest_config(repo: Path, pyproject: dict[str, object]) -> dict[str, object]:
    """Порядок как у самого pytest: pytest.ini, затем pyproject.toml, tox.ini, setup.cfg."""
    ini = _read_ini_section(repo / "pytest.ini", "pytest")
    if ini is not None:
        return ini
    section = _dig(pyproject, "tool", "pytest", "ini_options")
    if isinstance(section, dict):
        return section
    for name, header in (("tox.ini", "pytest"), ("setup.cfg", "tool:pytest")):
        ini = _read_ini_section(repo / name, header)
        if ini is not None:
            return ini
    return {}


def _read_ini_section(path: Path, header: str) -> dict[str, object] | None:
    text = _read_text(path)
    if text is None:
        return None
    # RawConfigParser: в ini-конфигах встречается '%(here)s', на котором интерполяция падает.
    parser = configparser.RawConfigParser()
    try:
        parser.read_string(text)
    except configparser.Error:
        return None
    if not parser.has_section(header):
        return None
    return dict(parser.items(header))


def _read_documents(repo: Path, paths: list[str]) -> dict[str, str]:
    """Текст файлов, где проект описывает окружение. Ключ — относительный POSIX-путь."""
    documents: dict[str, str] = {}
    for relative_path in paths:
        name = Path(relative_path).name.lower()
        suffix = Path(relative_path).suffix.lower()
        looks_relevant = (
            suffix in DOC_SUFFIXES
            or suffix in CONFIG_SUFFIXES
            or name.startswith(("docker-compose", "compose.", "dockerfile"))
            or relative_path.startswith(".github/workflows/")
        )
        if not looks_relevant:
            continue
        text = _read_text(repo / relative_path)
        if text is not None:
            documents[relative_path] = text
    return documents


def _load_dependencies(
    repo: Path, paths: list[str], pyproject: dict[str, object],
) -> tuple[set[str], str | None]:
    """Имена зависимостей и путь к requirements в формате pip (его читает `pip install -r`)."""
    names: set[str] = set()
    declared = _dig(pyproject, "project", "dependencies")
    if isinstance(declared, list):
        names |= {_dependency_name(str(item)) for item in declared}

    requirements_file: str | None = None
    for candidate in _requirements_candidates(paths):
        text = _read_text(repo / candidate)
        if text is None or not _looks_like_pip_requirements(text):
            continue
        requirements_file = candidate
        names |= {_dependency_name(line) for line in text.splitlines()}
        break

    if requirements_file is None:
        for candidate in paths:
            if Path(candidate).name.lower() in NON_PIP_LOCK_NAMES:
                LOGGER.warning(
                    "%s не в формате pip install -r, requirements_file остаётся пустым", candidate,
                )
                break
    return {name for name in names if name}, requirements_file


def _requirements_candidates(paths: list[str]) -> list[str]:
    """Сначала общепринятые имена в корне, затем прочие requirements*.lock и requirements*.txt."""
    root_files = [path for path in paths if "/" not in path]
    candidates = [name for name in PIP_REQUIREMENTS_NAMES if name in root_files]
    for suffix in (".lock", ".txt"):
        candidates += sorted(
            path for path in root_files
            if path.lower().startswith("requirements") and path.lower().endswith(suffix)
            and path not in candidates
        )
    return candidates


def _looks_like_pip_requirements(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line and not line.startswith("#")]
    if not lines or any(line.startswith("[") for line in lines):
        return False
    return any(PIP_REQUIREMENT_LINE.match(line) for line in lines if not line.startswith("-"))


def _dependency_name(line: str) -> str:
    match = DEPENDENCY_NAME.match(line.strip())
    return match.group(1).lower() if match else ""


# --- поля профиля ------------------------------------------------------------------------------

def _detect_python_version(repo: Path, paths: list[str], pyproject: dict[str, object]) -> str:
    """Берётся нижняя граница: образ обязан удовлетворять объявленному минимуму."""
    requires = _dig(pyproject, "project", "requires-python")
    if isinstance(requires, str):
        match = PYTHON_SPECIFIER.search(requires)
        if match:
            return f"{match.group(1)}.{match.group(2)}"

    target = _dig(pyproject, "tool", "ruff", "target-version")
    if isinstance(target, str):
        match = RUFF_TARGET.match(target.strip().lower())
        if match:
            return f"{match.group(1)}.{match.group(2)}"

    if ".python-version" in paths:
        text = _read_text(repo / ".python-version") or ""
        match = PLAIN_VERSION.search(text)
        if match:
            return f"{match.group(1)}.{match.group(2)}"

    options = _read_ini_section(repo / "setup.cfg", "options") or {}
    requires_cfg = options.get("python_requires")
    if isinstance(requires_cfg, str):
        match = PYTHON_SPECIFIER.search(requires_cfg)
        if match:
            return f"{match.group(1)}.{match.group(2)}"

    return DEFAULT_PYTHON_VERSION


def _detect_needs_postgres(
    dependency_names: set[str], pytest_config: dict[str, object], documents: dict[str, str],
) -> bool:
    if dependency_names & POSTGRES_DRIVERS:
        return True
    if any("postgres" in str(marker).lower() for marker in _as_list(pytest_config.get("markers"))):
        return True
    return any(POSTGRES_MENTION.search(text) for text in documents.values())


def _detect_postgres_major(documents: dict[str, str]) -> int | None:
    for _, text in sorted(documents.items()):
        match = POSTGRES_VERSION.search(text)
        if match:
            major = int(match.group(1))
            if 8 <= major <= 99:
                return major
    return None


def _detect_migration_command(paths: list[str]) -> list[str] | None:
    alembic = sorted((path for path in paths if Path(path).name == "alembic.ini"), key=len)
    if alembic:
        config = alembic[0]
        prefix = [] if config == "alembic.ini" else ["-c", config]
        return ["python", "-m", "alembic", *prefix, "upgrade", "head"]
    if "manage.py" in paths:
        return ["python", "manage.py", "migrate"]
    return None


def _detect_seed_sql(
    paths: list[str], testpaths: list[str], documents: dict[str, str],
) -> list[str]:
    """Сид — это .sql, который миграции не накатывают, а документация прогоняет отдельным psql."""
    documented: set[str] = set()
    for text in documents.values():
        documented |= set(PSQL_FILE.findall(text))

    seeds: set[str] = set()
    for relative_path in paths:
        parts = Path(relative_path).parts
        if Path(relative_path).suffix.lower() != ".sql":
            continue
        if parts[-1].lower().startswith("test_"):
            continue
        if any(part.lower() in TEST_DIR_NAMES for part in parts[:-1]):
            continue
        if any(relative_path.startswith(f"{testpath.strip('/')}/") for testpath in testpaths):
            continue
        tokens = set(re.split(r"[^a-z0-9]+", relative_path.lower()))
        if tokens & SEED_TOKENS or relative_path in documented:
            seeds.add(relative_path)
    return sorted(seeds)


def _detect_env_vars(repo: Path, paths: list[str], documents: dict[str, str]) -> dict[str, str]:
    """Только имена переменных и где они встретились. Значения не читаются — это возможные секреты."""
    found: dict[str, str] = {}

    for relative_path in paths:
        if Path(relative_path).suffix.lower() != ".py":
            continue
        text = _read_text(repo / relative_path)
        if text is None:
            continue
        for direct, accessor in ENV_IN_CODE.findall(text):
            found.setdefault(direct or accessor, f"читается в {relative_path}")

    for relative_path, text in sorted(documents.items()):
        for name in ENV_IN_SHELL.findall(text):
            found.setdefault(name, f"используется в командах {relative_path}")

    for relative_path in paths:
        if not Path(relative_path).name.lower().startswith(".env"):
            continue
        text = _read_text(repo / relative_path)
        if text is None:
            continue
        for line in text.splitlines():
            match = ENV_IN_DOTENV.match(line)
            if match:
                found.setdefault(match.group(1), f"объявлена в {relative_path}")

    return {name: purpose for name, purpose in sorted(found.items()) if name not in SHELL_ENV_VARS}


# --- мелочи ------------------------------------------------------------------------------------

def _dig(data: object, *keys: str) -> object:
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _as_list(value: object) -> list[str]:
    """Значение конфига: список TOML или ini-строка через пробелы и переводы строк."""
    if isinstance(value, str):
        return value.split()
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_SCAN_BYTES:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\0" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
