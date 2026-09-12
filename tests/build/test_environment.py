import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from harness.contracts import RunProfile, TestLists
from harness.build.environment import (
    render_dockerfile,
    safe_db_name,
    render_conftest,
    render_test_sh,
    write_environment,
)


def test_render_dockerfile_with_requirements() -> None:
    profile = RunProfile(
        python_version="3.11",
        requirements_file="requirements.lock",
        needs_postgres=True,
        postgres_major=16,
    )
    content = render_dockerfile(profile)
    assert "FROM python:3.11-slim-bookworm" in content
    assert "postgresql-16" in content
    assert "COPY requirements.lock /tmp/requirements.lock" in content
    assert "pip install --no-cache-dir -r /tmp/requirements.lock" in content
    assert "COPY repo/ /app/repo/" in content
    assert "WORKDIR /app/repo" in content


def test_render_dockerfile_without_requirements() -> None:
    profile = RunProfile(
        python_version="3.12",
        requirements_file=None,
        needs_postgres=False,
    )
    content = render_dockerfile(profile)
    assert "FROM python:3.12-slim-bookworm" in content
    assert "COPY None" not in content
    assert "requirements" not in content


def test_render_conftest_syntax_valid() -> None:
    profile = RunProfile(
        python_version="3.11",
        requirements_file="requirements.lock",
        pytest_pythonpath=["backend/src"],
        needs_postgres=True,
        postgres_major=16,
        migration_command=["python", "-m", "alembic", "upgrade", "head"],
        seed_sql_files=["sql/090_core_seed.sql"],
        env_vars={"FOO": "bar"},
    )
    content = render_conftest(profile)
    assert "backend/src" in content
    assert "NEEDS_POSTGRES = True" in content
    assert "POSTGRES_MAJOR = 16" in content
    assert "090_core_seed.sql" in content
    # Проверяем, что сгенерированный код синтаксически корректен как Python
    compile(content, "conftest.py", "exec")


def test_render_test_sh() -> None:
    lists = TestLists(
        fail_to_pass=["tests/test_a.py::test_1", "tests/test_a.py::test_2"],
        pass_to_pass=["tests/test_b.py::test_3"],
        anti_cheat=["tests/test_c.py::test_4"],
    )
    content = render_test_sh(lists)
    assert "EXPECTED_TESTS='4'" in content
    assert "/logs/verifier/reward.txt" in content
    assert "/logs/verifier/tests.xml" in content


def test_render_test_sh_expects_argument_count_for_list_runs() -> None:
    """Прогон по одному списку ожидает столько тестов, сколько ID ему передали.

    С зашитым общим числом тестов прогон по списку не мог получить reward 1 никогда —
    в том числе oracle/pass_to_pass, где все тесты проходят.
    """
    lists = TestLists(
        fail_to_pass=["tests/test_a.py::test_1", "tests/test_a.py::test_2"],
        pass_to_pass=["tests/test_b.py::test_3"],
        anti_cheat=["tests/test_c.py::test_4"],
    )
    content = render_test_sh(lists)

    # Без аргументов — полное число тестов из манифеста, с аргументами — их количество.
    assert "EXPECTED_TESTS='4'" in content
    assert 'EXPECTED_TESTS="$#"' in content
    assert "export EXPECTED_TESTS" in content
    assert "int(os.environ['EXPECTED_TESTS'])" in content
    # Старая форма с числом, зашитым в тело проверки, не должна остаться.
    assert "int('4')" not in content


def test_render_test_sh_is_valid_posix_sh(tmp_path: Path) -> None:
    if shutil.which("sh") is None:
        pytest.skip("нужен POSIX sh для проверки синтаксиса")
    lists = TestLists(
        fail_to_pass=["tests/test_a.py::test_1"],
        pass_to_pass=[],
        anti_cheat=[],
    )
    script = tmp_path / "test.sh"
    script.write_bytes(render_test_sh(lists).encode("utf-8"))

    result = subprocess.run(["sh", "-n", str(script)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")


def test_write_environment_cleans_repo() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        repo_src = tmp_path / "src_repo"
        repo_src.mkdir()
        (repo_src / "main.py").write_text("print('hello')", encoding="utf-8")
        (repo_src / "requirements.lock").write_text("pytest==9.0.2\n", encoding="utf-8")

        # Создаем «грязные» файлы, которые не должны попасть в environment/repo
        (repo_src / ".git").mkdir()
        (repo_src / ".git" / "config").write_text("git config", encoding="utf-8")
        (repo_src / ".venv").mkdir()
        (repo_src / ".venv" / "pip.exe").write_text("dummy", encoding="utf-8")
        (repo_src / "__pycache__").mkdir()
        (repo_src / "__pycache__" / "main.cpython-312.pyc").write_text("bytecode", encoding="utf-8")
        (repo_src / ".DS_Store").write_text("ds_store", encoding="utf-8")

        env_dir = tmp_path / "environment"
        profile = RunProfile(
            python_version="3.11",
            requirements_file="requirements.lock",
            needs_postgres=True,
            postgres_major=16,
        )

        write_environment(env_dir, profile, repo_src)

        assert (env_dir / "Dockerfile").exists()
        assert (env_dir / "requirements.lock").exists()
        assert (env_dir / "repo" / "main.py").exists()

        # Проверка отсутствия мусора
        assert not (env_dir / "repo" / ".git").exists()
        assert not (env_dir / "repo" / ".venv").exists()
        assert not (env_dir / "repo" / "__pycache__").exists()
        assert not (env_dir / "repo" / ".DS_Store").exists()


def test_render_conftest_does_not_set_env_vars_from_descriptions() -> None:
    """env_vars профиля — это «имя -> где встретилась», а не значения переменных.

    Раньше conftest делал os.environ.setdefault(имя, описание), и проект получал
    в DATABASE_URL фразу «читается в backend/migrations/env.py» вместо строки подключения.
    """
    profile = RunProfile(
        python_version="3.11",
        requirements_file="requirements.lock",
        pytest_pythonpath=["backend/src"],
        needs_postgres=True,
        postgres_major=16,
        env_vars={
            "DATABASE_URL": "читается в backend/migrations/env.py",
            "APP_SECRET": "читается в backend/src/config.py",
        },
    )

    content = render_conftest(profile)
    compile(content, "conftest.py", "exec")

    assert "os.environ.setdefault" not in content
    assert "ENV_VAR_SOURCES" in content
    # Описания остаются как справка, но в окружение не попадают.
    assert "читается в backend/migrations/env.py" in content

    # Исполняем шаблон: раньше на этом месте описания уезжали прямо в os.environ.
    namespace: dict = {}
    saved_path = list(sys.path)
    try:
        exec(compile(content, "conftest.py", "exec"), namespace)  # noqa: S102 - проверяем сам шаблон
    finally:
        sys.path[:] = saved_path
    assert namespace["ENV_VAR_SOURCES"]["APP_SECRET"] == "читается в backend/src/config.py"
    assert os.environ.get("APP_SECRET") is None
    assert os.environ.get("DATABASE_URL") != "читается в backend/migrations/env.py"


def test_render_conftest_uses_standard_postgres_endpoint() -> None:
    """База слушает 127.0.0.1:5432, иначе тест с psycopg.connect() не подключится."""
    profile = RunProfile(
        python_version="3.11", requirements_file=None,
        needs_postgres=True, postgres_major=16,
    )

    content = render_conftest(profile)
    compile(content, "conftest.py", "exec")

    assert "POSTGRES_PORT = 5432" in content
    assert 'POSTGRES_LISTEN = "127.0.0.1"' in content
    assert "listen_addresses={POSTGRES_LISTEN}" in content
    # Случайный порт был причиной "connection to 127.0.0.1:5432 refused".
    assert "_get_free_port" not in content
    # Стандартные переменные libpq: с ними работает и подключение без аргументов.
    for variable in ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER"):
        assert f'os.environ["{variable}"]' in content


def test_render_conftest_exposes_neutral_dsn_variables() -> None:
    """Каноническое имя переменной не привязано к проекту, на котором харнесс отлаживали."""
    profile = RunProfile(
        python_version="3.11", requirements_file=None,
        needs_postgres=True, postgres_major=16,
    )

    content = render_conftest(profile, "team/case-001")

    assert 'os.environ["CASE_DSN"]' in content
    assert 'os.environ["CASE_DATABASE_URL"]' in content
    assert "meridian" not in content


def test_render_conftest_names_database_after_case_id() -> None:
    profile = RunProfile(
        python_version="3.11", requirements_file=None,
        needs_postgres=True, postgres_major=16,
    )

    content = render_conftest(profile, "hackathon/settlement-001")

    assert 'CASE_DB_NAME = "hackathon_settlement_001"' in content


@pytest.mark.parametrize(("case_id", "expected"), [
    ("hackathon/settlement-001", "hackathon_settlement_001"),
    ("team-x/Case_42", "team_x_case_42"),
    ("123/abc", "case_123_abc"),
    ("", "case_db"),
    ("!!!/???", "case_db"),
])
def test_safe_db_name(case_id: str, expected: str) -> None:
    name = safe_db_name(case_id)
    assert name == expected
    # Идентификатор PostgreSQL: не длиннее 63 байт и не начинается с цифры.
    assert len(name) <= 63
    assert not name[0].isdigit()


def test_render_conftest_maps_repository_env_vars_by_format() -> None:
    """Проект получает строку подключения под своими именами: DSN или URL по формату имени."""
    profile = RunProfile(
        python_version="3.11", requirements_file=None,
        needs_postgres=True, postgres_major=16,
        env_vars={
            "MERIDIAN_DSN": "читается в src/db.py",
            "DATABASE_URL": "читается в migrations/env.py",
            "APP_SECRET": "читается в src/config.py",
        },
    )

    content = render_conftest(profile, "team/case-001")
    namespace: dict = {}
    saved_path = list(sys.path)
    try:
        exec(compile(content, "conftest.py", "exec"), namespace)  # noqa: S102 - проверяем шаблон
    finally:
        sys.path[:] = saved_path

    is_db_var, wants_url = namespace["_is_db_var"], namespace["_wants_url"]
    assert is_db_var("MERIDIAN_DSN") and not wants_url("MERIDIAN_DSN")
    assert is_db_var("DATABASE_URL") and wants_url("DATABASE_URL")
    # Переменная, не имеющая отношения к базе, строку подключения не получает.
    assert not is_db_var("APP_SECRET")
    assert os.environ.get("APP_SECRET") is None
