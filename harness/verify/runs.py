"""Матрица прогонов. Владелец: №3.

build; base/full; base/{fail_to_pass,pass_to_pass,anti_cheat}; oracle/full; oracle/{...};
repeat/base/full; repeat/oracle/full; mutant/<name>; collect (pytest --collect-only).
Каждый прогон — свежий контейнер; результаты и логи в evidence/<name>/.
"""
from __future__ import annotations

from pathlib import Path

from harness.contracts import Limits, Mutant, RunResult, TestLists


def run_collect(task_dir: Path, evidence_dir: Path, image: str, limits: Limits) -> RunResult:
    raise NotImplementedError


def run_base_and_oracle(
    task_dir: Path, evidence_dir: Path, image: str, lists: TestLists, limits: Limits,
    *, repeat: bool = True,
) -> list[RunResult]:
    raise NotImplementedError


def run_mutants(
    task_dir: Path, evidence_dir: Path, image: str, lists: TestLists, limits: Limits,
    mutants: list[Mutant],
) -> list[RunResult]:
    raise NotImplementedError
