"""Определение профиля запуска проекта. Владелец: №1.

Источники: pyproject.toml ([tool.pytest.ini_options]), requirements.lock / requirements.txt,
alembic.ini, README. Для meridian ожидается: python 3.11, requirements.lock, pythonpath backend/src,
PostgreSQL 16, миграция `python -m alembic upgrade head`, сид sql/090_core_seed.sql.
"""
from __future__ import annotations

from pathlib import Path

from harness.contracts import RunProfile


def detect_run_profile(repo: Path) -> RunProfile:
    raise NotImplementedError
