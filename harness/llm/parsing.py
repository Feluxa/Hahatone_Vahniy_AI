"""Разбор ответов LLM (JSON и файлы в fenced-блоках), с понятными ошибками для повтора. Владелец: №2."""
from __future__ import annotations

def extract_json(text: str) -> object:
    raise NotImplementedError


def extract_files(text: str) -> dict[str, str]:
    raise NotImplementedError
