"""Ремонт черновика по Verdict: меняется только то, на что указывает Problem.target. Владелец: №2."""
from __future__ import annotations

from harness.contracts import CaseDraft, RepoContext, Verdict
from harness.llm.client import LlmClient


def repair(client: LlmClient, context: RepoContext, draft: CaseDraft, verdict: Verdict, log_excerpts: dict[str, str]) -> CaseDraft:
    raise NotImplementedError
