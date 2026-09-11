"""Генерация solution/solve.sh. Владелец: №2."""
from __future__ import annotations

from harness.contracts import CaseSpec, RepoContext
from harness.llm.client import LlmClient


def write_solution(client: LlmClient, context: RepoContext, spec: CaseSpec) -> dict[str, str]:
    raise NotImplementedError
