"""Поиск недоверенных файлов. Владелец: №1.

Недоверенные: импортированные тикеты, фиды, внешние сообщения (например meridian/DOCS/imported/*).
Их содержимое НЕ передаётся в LLM; в контекст попадает только путь и пометка Trust.UNTRUSTED.
Эти пути также становятся кандидатами на anti_cheat «файл не изменён».
"""
from __future__ import annotations

from pathlib import Path


def find_untrusted(repo: Path) -> list[str]:
    raise NotImplementedError
