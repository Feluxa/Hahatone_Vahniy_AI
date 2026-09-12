"""Шаблоны окружения и тестовой обвязки. Владелец: №3.

Решения из плана:
  * образ содержит PostgreSQL 16 и Python 3.11, зависимости ставятся при сборке из requirements.lock;
  * стартовый код в /app/repo; tests/ и solution/ в образ не копируются;
  * БД поднимается в session-фикстуре tests/conftest.py (initdb во временной папке, не от root),
    затем alembic upgrade head из /app/repo — ПОСЛЕ solve.sh, потому что решение может менять SQL;
  * tests/test.sh пишет 0 в /logs/verifier/reward.txt, запускает pytest с --junitxml, и пишет 1 только если
    собрано ровно ожидаемое число тестов и нет failure/error/skipped.
Сами тексты шаблонов лежат в harness/build/templates/.
"""
from __future__ import annotations

import shutil
import re
from pathlib import Path
from string import Template

from harness.contracts import RunProfile, TestLists

TEMPLATES_DIR = Path(__file__).parent / "templates"

DEFAULT_DB_NAME = "case_db"
UNSAFE_DB_CHARS = re.compile(r"[^a-z0-9_]+")


def safe_db_name(case_id: str) -> str:
    """Имя базы из case_id: нижний регистр, только буквы, цифры и подчёркивание.

    Идентификатор PostgreSQL не может начинаться с цифры и длиннее 63 байт не бывает.
    """
    cleaned = UNSAFE_DB_CHARS.sub("_", case_id.strip().lower()).strip("_")
    if not cleaned:
        return DEFAULT_DB_NAME
    if not cleaned[0].isalpha():
        cleaned = f"case_{cleaned}"
    return cleaned[:63]


def render_dockerfile(profile: RunProfile) -> str:
    tmpl_path = TEMPLATES_DIR / "Dockerfile.tmpl"
    tmpl_str = tmpl_path.read_text(encoding="utf-8")

    install_req = ""
    if profile.requirements_file:
        install_req = (
            f"COPY {profile.requirements_file} /tmp/{profile.requirements_file}\n"
            f"RUN python -m pip install --no-cache-dir -r /tmp/{profile.requirements_file}"
        )

    mapping = {
        "python_version": profile.python_version or "3.11",
        "postgres_major": str(profile.postgres_major or 16),
        "install_requirements": install_req,
    }
    return Template(tmpl_str).substitute(mapping)


def render_conftest(profile: RunProfile, case_id: str = "") -> str:
    tmpl_path = TEMPLATES_DIR / "conftest.py.tmpl"
    tmpl_str = tmpl_path.read_text(encoding="utf-8")
    mapping = {
        "db_name": safe_db_name(case_id),
        "pytest_pythonpath": repr(profile.pytest_pythonpath),
        "needs_postgres": "True" if profile.needs_postgres else "False",
        "postgres_major": str(profile.postgres_major or 16),
        "migration_cmd": repr(profile.migration_command),
        "seed_sql_files": repr(profile.seed_sql_files),
        "env_vars": repr(profile.env_vars),
    }
    return Template(tmpl_str).substitute(mapping)


def render_test_sh(lists: TestLists) -> str:
    tmpl_path = TEMPLATES_DIR / "test.sh.tmpl"
    tmpl_str = tmpl_path.read_text(encoding="utf-8")
    mapping = {
        "expected_tests": str(len(lists.all_ids())),
    }
    return Template(tmpl_str).substitute(mapping)


def write_environment(env_dir: Path, profile: RunProfile, repo_copy: Path) -> None:
    """Создаёт environment/Dockerfile (+ requirements) и кладёт repo_copy в environment/repo/."""
    env_dir.mkdir(parents=True, exist_ok=True)

    # 1. Запись Dockerfile
    dockerfile_content = render_dockerfile(profile)
    (env_dir / "Dockerfile").write_text(dockerfile_content, encoding="utf-8")

    # 2. Копирование requirements файла при наличии
    if profile.requirements_file:
        src_req = repo_copy / profile.requirements_file
        if src_req.exists():
            dest_req = env_dir / profile.requirements_file
            dest_req.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_req, dest_req)

    # 3. Копирование репозитория в environment/repo/ без мусора
    target_repo = env_dir / "repo"
    if target_repo.exists():
        shutil.rmtree(target_repo)

    def _ignore(path: str, names: list[str]) -> set[str]:
        ignored = {".git", ".venv", "__pycache__", ".pytest_cache", ".DS_Store"}
        return {n for n in names if n in ignored or n.endswith(".pyc")}

    shutil.copytree(repo_copy, target_repo, ignore=_ignore)

