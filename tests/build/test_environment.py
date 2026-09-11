from pathlib import Path
import tempfile

from harness.contracts import RunProfile, TestLists
from harness.build.environment import (
    render_dockerfile,
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
    assert "expected = int('4')" in content
    assert "/logs/verifier/reward.txt" in content
    assert "/logs/verifier/tests.xml" in content


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
