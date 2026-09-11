"""Чистая копия репозитория. Владелец: №1.

Используется для workspace (где работает харнесс) и для task/environment/repo/.
Исходник только читается. В копию не попадают артефакты из IGNORED_NAMES (PROTOCOL.md, раздел 3).
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

IGNORED_NAMES: frozenset[str] = frozenset({
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".DS_Store", "node_modules", ".idea", ".vscode",
})
IGNORED_SUFFIXES: tuple[str, ...] = (".pyc", ".pyo")


class WorkspaceError(ValueError):
    """Копию сделать нельзя: нет исходника, назначение занято, символьная ссылка."""


def copy_clean(src: Path, dst: Path) -> list[str]:
    """Копирует src в dst (dst не должен существовать). Возвращает список пропущенных путей.

    Пропущенное — относительные POSIX-пути, отсортированные; пропущенная папка указывается
    один раз, без содержимого. Права доступа сохраняются: в репозитории могут быть скрипты,
    которым в контейнере нужен бит исполняемости.

    Если копирование сорвалось (символьная ссылка, нет доступа, кончилось место), незавершённая
    dst удаляется и наружу идёт исходная ошибка: иначе следующий запуск упал бы на «назначение
    уже существует» и настоящая причина потерялась бы.
    """
    if not src.exists():
        raise WorkspaceError(f"нечего копировать: {src}")
    if not src.is_dir():
        raise WorkspaceError(f"источник не папка: {src}")
    if dst.exists():
        raise WorkspaceError(f"назначение уже существует, перезапись запрещена: {dst}")
    skipped: list[str] = []
    dst.mkdir(parents=True)
    try:
        _copy_dir(src, src, dst, skipped)
    except BaseException:
        shutil.rmtree(dst, ignore_errors=True)  # ignore_errors, чтобы не заслонить исходную ошибку
        raise
    return sorted(skipped)


def _is_ignored(name: str) -> bool:
    """Совпадение только точное по имени или по суффиксу: .gitignore — не .git, venv_tools — не venv."""
    return name in IGNORED_NAMES or name.endswith(IGNORED_SUFFIXES)


def _copy_dir(root: Path, source: Path, target: Path, skipped: list[str]) -> None:
    with os.scandir(source) as entries:
        for entry in entries:
            path = Path(entry.path)
            relative_path = path.relative_to(root).as_posix()
            if entry.is_symlink():
                raise WorkspaceError(f"символьная ссылка в исходном репозитории: {relative_path}")
            if _is_ignored(entry.name):
                skipped.append(relative_path)
            elif entry.is_dir(follow_symlinks=False):
                (target / entry.name).mkdir()
                _copy_dir(root, path, target / entry.name, skipped)
            elif entry.is_file(follow_symlinks=False):
                shutil.copy2(path, target / entry.name)
            else:  # сокет, fifo, устройство
                raise WorkspaceError(f"не обычный файл в исходном репозитории: {relative_path}")
