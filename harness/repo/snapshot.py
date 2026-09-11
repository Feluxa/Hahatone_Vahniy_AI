"""Хэш снимка исходного репозитория. Владелец: №1.

Алгоритм (PROTOCOL.md, раздел 2):
  все обычные файлы, включая скрытые -> относительный POSIX-путь -> лексикографическая сортировка
  -> для каждого строка: путь + "\0" + sha256(содержимое) lowercase hex + "\n"
  -> SHA-256 конкатенации строк в UTF-8.
Символьные ссылки в исходном наборе не используются; если встретились — это ошибка входа.
Вызывается дважды: до любой работы и в самом конце (проверка, что исходник не изменён).
"""
from __future__ import annotations

from pathlib import Path


def compute_snapshot_sha256(root: Path) -> str:
    raise NotImplementedError


def list_regular_files(root: Path) -> list[str]:
    """Отсортированные относительные POSIX-пути всех обычных файлов, включая скрытые."""
    raise NotImplementedError
