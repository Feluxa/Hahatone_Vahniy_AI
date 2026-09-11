"""Хэш снимка исходного репозитория. Владелец: №1.

Алгоритм (PROTOCOL.md, раздел 2):
  все обычные файлы, включая скрытые -> относительный POSIX-путь -> лексикографическая сортировка
  -> для каждого строка: путь + "\0" + sha256(содержимое) lowercase hex + "\n"
  -> SHA-256 конкатенации строк в UTF-8.
Символьные ссылки в исходном наборе не используются; если встретились — это ошибка входа.
Вызывается дважды: до любой работы и в самом конце (проверка, что исходник не изменён).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

CHUNK_SIZE = 1 << 20


class SnapshotError(ValueError):
    """Репозиторий не годится для снимка: нет папки, символьная ссылка, не обычный файл."""


def compute_snapshot_sha256(root: Path) -> str:
    snapshot = hashlib.sha256()
    for relative_path in list_regular_files(root):
        line = f"{relative_path}\0{_sha256_file(root / relative_path)}\n"
        snapshot.update(line.encode("utf-8"))
    return snapshot.hexdigest()


def list_regular_files(root: Path) -> list[str]:
    """Отсортированные относительные POSIX-пути всех обычных файлов, включая скрытые."""
    if not root.exists():
        raise SnapshotError(f"репозитория нет: {root}")
    if not root.is_dir():
        raise SnapshotError(f"путь к репозиторию не папка: {root}")
    found: list[str] = []
    _collect(root, root, found)
    # Сортировка по полному относительному пути, а не по папкам: 'a-b.txt' < 'a.txt' < 'a/b.txt'.
    return sorted(found)


def _collect(root: Path, directory: Path, found: list[str]) -> None:
    with os.scandir(directory) as entries:
        for entry in entries:
            path = Path(entry.path)
            relative_path = path.relative_to(root).as_posix()
            if entry.is_symlink():
                raise SnapshotError(f"символьная ссылка в исходном репозитории: {relative_path}")
            if entry.is_dir(follow_symlinks=False):
                _collect(root, path, found)
            elif entry.is_file(follow_symlinks=False):
                found.append(relative_path)
            else:  # сокет, fifo, устройство — в снимок не попадают, молча пропустить нельзя
                raise SnapshotError(f"не обычный файл в исходном репозитории: {relative_path}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()
