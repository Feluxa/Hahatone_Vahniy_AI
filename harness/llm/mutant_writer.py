"""LLM-мутанты: правдоподобные неправильные решения в виде патчей. Владелец: №2."""
from __future__ import annotations

from harness.contracts import CaseDraft, Mutant, RepoContext
from harness.llm.client import LlmClient


def write_mutants(client: LlmClient, context: RepoContext, draft: CaseDraft, oracle_diff: str) -> list[Mutant]:
    raise NotImplementedError
