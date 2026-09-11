"""Чистая копия репозитория. Владелец: №1.

Используется для workspace (где работает харнесс) и для task/environment/repo/.
Исходник только читается. В копию не попадают артефакты из IGNORED_NAMES (PROTOCOL.md, раздел 3).
"""
from __future__ import annotations

from pathlib import Path

IGNORED_NAMES: frozenset[str] = frozenset({
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".DS_Store", "node_modules", ".idea", ".vscode",
})
IGNORED_SUFFIXES: tuple[str, ...] = (".pyc", ".pyo")


def copy_clean(src: Path, dst: Path) -> list[str]:
    """Копирует src в dst (dst не должен существовать). Возвращает список пропущенных путей."""
    raise NotImplementedError
