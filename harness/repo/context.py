"""Сбор RepoContext под бриф. Владелец: №1.

Шаги: ключевые слова брифа -> поиск по путям, символам, SQL-объектам -> расширение по импортам на 1 шаг
-> документация компонента и правила проекта -> существующие тесты компонента.
Результат для settlement-001 сохранить в fixtures/repo_context.settlement.json (нужен №2 завтра).
"""
from __future__ import annotations

from pathlib import Path

from harness.contracts import RepoContext


def build_context(repo: Path, brief: str, *, max_files: int = 20) -> RepoContext:
    raise NotImplementedError
