"""Мутанты. Владелец: №3 (hunk-revert); LLM-мутанты приходят от №2 в том же формате Mutant.

hunk-revert: diff /app/repo до и после solve.sh, откат каждого hunk по отдельности.
Каждый мутант обязан давать reward 0. Мутант, чей патч не применился, отбрасывается и не считается.
"""
from __future__ import annotations

from pathlib import Path

from harness.contracts import Mutant


def oracle_diff(base_repo: Path, oracle_repo: Path) -> str:
    raise NotImplementedError


def hunk_revert_mutants(diff: str) -> list[Mutant]:
    raise NotImplementedError
