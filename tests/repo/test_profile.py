"""Профиль запуска проекта (PLAN §1.4, §5.3).

Источники общие для любого Python-репозитория: pyproject/pytest-конфиг, requirements, alembic,
документация. Профиль — эвристика, поэтому неполнота источников не обрывает прогон: ProfileError
только на структурных проблемах, всё остальное деградирует до None и пустых списков.
"""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path

import pytest

from harness.contracts import RunProfile
from harness.repo.profile import DEFAULT_PYTHON_VERSION, ProfileError, detect_run_profile
from tests.repo.tiny_repo import build_repo

MERIDIAN = Path(__file__).resolve().parents[2] / "materials" / "hackathon-participants" / "meridian"
needs_meridian = pytest.mark.skipif(not MERIDIAN.is_dir(), reason="materials/ не выложены локально")

PYPROJECT = b"""[project]
name = "demo"
requires-python = ">=3.12"
dependencies = ["pydantic==2.11.3"]

[tool.pytest.ini_options]
pythonpath = ["backend/src"]
testpaths = ["tests"]
markers = ["postgres: requires isolated PostgreSQL with migrations"]

[tool.ruff]
target-version = "py39"
"""

README = b"""# Demo

Needs a separate PostgreSQL 15. Set `DATABASE_URL` and `$SERVICE_DSN`.

```sh
python -m alembic upgrade head
psql "$SERVICE_DSN" -v ON_ERROR_STOP=1 -f sql/090_core_seed.sql
psql "$SERVICE_DSN" -v ON_ERROR_STOP=1 -f tests/sql/test_smoke.sql
```
"""

FULL_REPO: dict[str, bytes] = {
    "pyproject.toml": PYPROJECT,
    "README.md": README,
    "requirements.lock": b"alembic==1.15.2\npsycopg[binary]==3.2.6\npydantic==2.11.3\n",
    "requirements.txt": b"alembic\npsycopg\n",
    "alembic.ini": b"[alembic]\nscript_location = %(here)s/backend/migrations\n",
    "backend/migrations/env.py": (
        b"import os\n\nengine = create_engine(os.environ[\"DATABASE_URL\"])\n"
    ),
    "backend/src/app.py": b"VALUE = 1\n",
    "sql/001_schema.sql": b"CREATE SCHEMA demo;\n",
    "sql/090_core_seed.sql": b"INSERT INTO demo.t VALUES (1);\n",
    "tests/sql/test_smoke.sql": b"SELECT 1;\n",
    "tests/test_app.py": b"def test_app() -> None:\n    pass\n",
}

FULL_PROFILE = RunProfile(
    python_version="3.12",
    requirements_file="requirements.lock",
    pytest_pythonpath=["backend/src"],
    pytest_testpaths=["tests"],
    needs_postgres=True,
    postgres_major=15,
    migration_command=["python", "-m", "alembic", "upgrade", "head"],
    seed_sql_files=["sql/090_core_seed.sql"],
    env_vars={},
)


def without_env(profile: RunProfile) -> RunProfile:
    return dataclasses.replace(profile, env_vars={})


def test_full_repo(tmp_path: Path) -> None:
    """requires-python важнее ruff target-version, лок важнее requirements.txt, сид отделён от тестов."""
    root = build_repo(tmp_path / "repo", FULL_REPO)
    assert without_env(detect_run_profile(root)) == FULL_PROFILE


def test_env_vars_collect_names_with_sources(tmp_path: Path) -> None:
    root = build_repo(tmp_path / "repo", FULL_REPO)
    env_vars = detect_run_profile(root).env_vars
    assert set(env_vars) == {"DATABASE_URL", "SERVICE_DSN"}
    assert "backend/migrations/env.py" in env_vars["DATABASE_URL"]
    assert "README.md" in env_vars["SERVICE_DSN"]


def test_env_values_never_leak(tmp_path: Path) -> None:
    """Из .env берутся только имена: значения — потенциальные секреты (CLAUDE.md, раздел «Ключи»)."""
    files = dict(FULL_REPO)
    files[".env.example"] = b"SERVICE_DSN=host=db dbname=demo\nAPI_TOKEN=hunter2\n"
    root = build_repo(tmp_path / "repo", files)
    profile = detect_run_profile(root)
    assert "API_TOKEN" in profile.env_vars
    assert "hunter2" not in repr(profile)
    assert "dbname=demo" not in repr(profile)


def test_shell_variables_are_ignored(tmp_path: Path) -> None:
    root = build_repo(tmp_path / "repo", {"README.md": b"Run `$HOME/bin/x` with $PATH and $APP_DSN.\n"})
    assert set(detect_run_profile(root).env_vars) == {"APP_DSN"}


# --- pytest-конфиг -----------------------------------------------------------------------------

INI_SOURCES = {
    "pytest.ini": b"[pytest]\npythonpath = backend/src lib\ntestpaths = tests\n",
    "tox.ini": b"[tox]\nenvlist = py311\n\n[pytest]\npythonpath =\n    backend/src\n    lib\ntestpaths = tests\n",
    "setup.cfg": b"[tool:pytest]\npythonpath =\n    backend/src\n    lib\ntestpaths = tests\n",
}


@pytest.mark.parametrize("name", sorted(INI_SOURCES))
def test_pytest_config_from_ini_files(tmp_path: Path, name: str) -> None:
    """Значение в ini — строка через пробел или через перевод строки, а не список TOML."""
    root = build_repo(tmp_path / "repo", {name: INI_SOURCES[name]})
    profile = detect_run_profile(root)
    assert profile.pytest_pythonpath == ["backend/src", "lib"]
    assert profile.pytest_testpaths == ["tests"]


def test_pytest_ini_wins_over_pyproject(tmp_path: Path) -> None:
    root = build_repo(tmp_path / "repo", {
        "pyproject.toml": PYPROJECT,
        "pytest.ini": b"[pytest]\npythonpath = src\ntestpaths = checks\n",
    })
    profile = detect_run_profile(root)
    assert profile.pytest_pythonpath == ["src"]
    assert profile.pytest_testpaths == ["checks"]


# --- версия Python -----------------------------------------------------------------------------

PYTHON_VERSION_SOURCES = [
    ({"pyproject.toml": b"[project]\nrequires-python = \">=3.10,<4.0\"\n"}, "3.10"),
    ({"pyproject.toml": b"[project]\nrequires-python = \"~=3.13\"\n"}, "3.13"),
    ({"pyproject.toml": b"[tool.ruff]\ntarget-version = \"py311\"\n"}, "3.11"),
    ({".python-version": b"3.12.4\n"}, "3.12"),
    ({"setup.cfg": b"[options]\npython_requires = >=3.9\n"}, "3.9"),
    ({"README.md": b"# demo\n"}, DEFAULT_PYTHON_VERSION),
]


@pytest.mark.parametrize(("files", "expected"), PYTHON_VERSION_SOURCES)
def test_python_version_sources(tmp_path: Path, files: dict[str, bytes], expected: str) -> None:
    root = build_repo(tmp_path / "repo", files)
    assert detect_run_profile(root).python_version == expected


# --- requirements ------------------------------------------------------------------------------

def test_requirements_txt_when_no_lock(tmp_path: Path) -> None:
    root = build_repo(tmp_path / "repo", {"requirements.txt": b"pytest==9.0.2\n"})
    assert detect_run_profile(root).requirements_file == "requirements.txt"


def test_non_pip_lock_is_not_offered(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """poetry.lock не ставится через pip install -r: Dockerfile у №3 упал бы на сборке."""
    root = build_repo(tmp_path / "repo", {
        "poetry.lock": b"[[package]]\nname = \"pytest\"\nversion = \"9.0.2\"\n",
        "pyproject.toml": b"[project]\nname = \"demo\"\n",
    })
    with caplog.at_level(logging.WARNING, logger="harness.repo.profile"):
        assert detect_run_profile(root).requirements_file is None
    assert "poetry.lock" in caplog.text


def test_requirements_file_in_wrong_format_is_rejected(tmp_path: Path) -> None:
    root = build_repo(tmp_path / "repo", {"requirements.lock": b"[[package]]\nname = \"pytest\"\n"})
    assert detect_run_profile(root).requirements_file is None


# --- PostgreSQL и миграции ---------------------------------------------------------------------

def test_dsn_scheme_does_not_become_a_version(tmp_path: Path) -> None:
    root = build_repo(tmp_path / "repo", {
        "README.md": b"Set DATABASE_URL to postgresql+psycopg://user@host/db\n",
    })
    profile = detect_run_profile(root)
    assert profile.needs_postgres is True
    assert profile.postgres_major is None


def test_postgres_from_compose_image_tag(tmp_path: Path) -> None:
    root = build_repo(tmp_path / "repo", {"docker-compose.yml": b"services:\n  db:\n    image: postgres:16\n"})
    profile = detect_run_profile(root)
    assert profile.needs_postgres is True
    assert profile.postgres_major == 16


def test_untrusted_files_do_not_feed_the_profile(tmp_path: Path) -> None:
    """postgres_major уезжает в Dockerfile, поэтому инъекция не должна влиять на профиль.

    'DOCS/imported/ticket.txt' сортируется раньше 'README.md', так что без исключения
    недоверенных файлов в профиль попала бы девятка из тикета.
    """
    root = build_repo(tmp_path / "repo", {
        "README.md": b"PostgreSQL 16 required.\n",
        "DOCS/imported/ticket.txt": b"Use PostgreSQL 9 and set $EVIL_TOKEN.\n",
    })
    profile = detect_run_profile(root)
    assert profile.postgres_major == 16
    assert "EVIL_TOKEN" not in profile.env_vars


def test_no_postgres_signals(tmp_path: Path) -> None:
    root = build_repo(tmp_path / "repo", {
        "pyproject.toml": b"[project]\nname = \"demo\"\n",
        "requirements.txt": b"pytest==9.0.2\n",
    })
    profile = detect_run_profile(root)
    assert profile.needs_postgres is False
    assert profile.postgres_major is None
    assert profile.migration_command is None


def test_nested_alembic_ini_adds_config_flag(tmp_path: Path) -> None:
    root = build_repo(tmp_path / "repo", {"backend/alembic.ini": b"[alembic]\nscript_location = m\n"})
    assert detect_run_profile(root).migration_command == [
        "python", "-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head",
    ]


def test_django_migration_command(tmp_path: Path) -> None:
    root = build_repo(tmp_path / "repo", {"manage.py": b"import django\n"})
    assert detect_run_profile(root).migration_command == ["python", "manage.py", "migrate"]


# --- сид ---------------------------------------------------------------------------------------

def test_seed_sql_excludes_tests(tmp_path: Path) -> None:
    root = build_repo(tmp_path / "repo", {
        "pyproject.toml": b"[tool.pytest.ini_options]\ntestpaths = [\"checks\"]\n",
        "sql/090_seed.sql": b"INSERT INTO t VALUES (1);\n",
        "checks/seed_cases.sql": b"SELECT 1;\n",
        "tests/test_seed.sql": b"SELECT 1;\n",
    })
    assert detect_run_profile(root).seed_sql_files == ["sql/090_seed.sql"]


def test_seed_sql_from_documented_psql_command(tmp_path: Path) -> None:
    """Имя без слова seed, но документация прогоняет файл отдельно от миграций."""
    root = build_repo(tmp_path / "repo", {
        "README.md": b"```sh\npsql \"$DSN\" -v ON_ERROR_STOP=1 -f sql/095_reference_rows.sql\n```\n",
        "sql/095_reference_rows.sql": b"INSERT INTO t VALUES (1);\n",
    })
    assert detect_run_profile(root).seed_sql_files == ["sql/095_reference_rows.sql"]


# --- деградация и ошибки -----------------------------------------------------------------------

def test_empty_repo_degrades_without_raising(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    assert detect_run_profile(root) == RunProfile(
        python_version=DEFAULT_PYTHON_VERSION,
        requirements_file=None,
        pytest_pythonpath=[],
        pytest_testpaths=[],
        needs_postgres=False,
        postgres_major=None,
        migration_command=None,
        seed_sql_files=[],
        env_vars={},
    )


def test_broken_pyproject_raises(tmp_path: Path) -> None:
    root = build_repo(tmp_path / "repo", {"pyproject.toml": b"[project\nname = broken\n"})
    with pytest.raises(ProfileError):
        detect_run_profile(root)


def test_missing_repo_raises(tmp_path: Path) -> None:
    with pytest.raises(ProfileError):
        detect_run_profile(tmp_path / "нет")


def test_repo_is_not_a_directory_raises(tmp_path: Path) -> None:
    file_path = tmp_path / "repo.txt"
    file_path.write_bytes(b"x")
    with pytest.raises(ProfileError):
        detect_run_profile(file_path)


# --- meridian ----------------------------------------------------------------------------------

@needs_meridian
def test_meridian_profile() -> None:
    profile = detect_run_profile(MERIDIAN)
    assert without_env(profile) == RunProfile(
        python_version="3.11",
        requirements_file="requirements.lock",
        pytest_pythonpath=["backend/src"],
        pytest_testpaths=["tests"],
        needs_postgres=True,
        postgres_major=16,
        migration_command=["python", "-m", "alembic", "upgrade", "head"],
        seed_sql_files=["sql/090_core_seed.sql"],
        env_vars={},
    )
    assert set(profile.env_vars) == {"DATABASE_URL", "MERIDIAN_DSN"}
