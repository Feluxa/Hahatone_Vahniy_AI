"""Оркестрация и repair loop. Владелец: №4.

input -> snapshot -> workspace -> context -> spec/instruction -> tests -> solution -> task/ -> static checks
-> verify_case -> (repair, максимум MAX_REPAIR_ITERATIONS) -> evidence -> snapshot again -> result.json
"""
from __future__ import annotations

from harness.contracts import CaseInput, CaseResult

MAX_REPAIR_ITERATIONS = 3


def run(case: CaseInput) -> CaseResult:
    raise NotImplementedError
