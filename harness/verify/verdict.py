"""Итоговое решение по прогонам. Владелец: №3.

Проверяет всё из раздела 10 плана, что касается прогонов, и возвращает Problem с категорией
и target (что чинить в repair loop). Статические проблемы (static_checks, №4) передаются снаружи.
"""
from __future__ import annotations

from harness.contracts import Problem, RunResult, TestLists, Verdict


def decide(runs: list[RunResult], lists: TestLists, static_problems: list[Problem]) -> Verdict:
    raise NotImplementedError
