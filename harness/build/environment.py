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

from pathlib import Path

from harness.contracts import RunProfile, TestLists

TEMPLATES_DIR = Path(__file__).parent / "templates"


def render_dockerfile(profile: RunProfile) -> str:
    raise NotImplementedError


def render_conftest(profile: RunProfile) -> str:
    raise NotImplementedError


def render_test_sh(lists: TestLists) -> str:
    raise NotImplementedError


def write_environment(env_dir: Path, profile: RunProfile, repo_copy: Path) -> None:
    """Создаёт environment/Dockerfile (+ requirements) и кладёт repo_copy в environment/repo/."""
    raise NotImplementedError
