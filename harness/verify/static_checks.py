"""Статические проверки папки task/. Владелец: №4.

* структура task/ по протоколу, без логов, кэшей, .git, .venv;
* нет skip/xfail/importorskip в тестах;
* instruction.md не содержит имён тестов, путей tests/ и solution/, фрагментов решения;
* solve.sh не ссылается на /tests и /logs.
Сверка собранных ID со списками делается по прогону collect (verdict.py, №3).
"""
from __future__ import annotations

from pathlib import Path

from harness.contracts import Problem, TestLists


def check_task_folder(task_dir: Path, lists: TestLists) -> list[Problem]:
    raise NotImplementedError
