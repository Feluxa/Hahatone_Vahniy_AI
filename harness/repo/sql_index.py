"""Индекс SQL-объектов: схемы, таблицы, колонки, констрейнты, функции, вьюхи. Владелец: №1."""
from __future__ import annotations

from pathlib import Path

from harness.contracts import SqlObject


def index_sql(repo: Path, paths: list[str]) -> list[SqlObject]:
    raise NotImplementedError
