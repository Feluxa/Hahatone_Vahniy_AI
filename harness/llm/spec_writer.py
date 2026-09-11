"""Спецификация задачи и instruction.md. Владелец: №2."""
from __future__ import annotations

from harness.contracts import CaseSpec, Language, RepoContext
from harness.llm.client import LlmClient


def write_spec(client: LlmClient, context: RepoContext) -> CaseSpec:
    raise NotImplementedError


def write_instruction(client: LlmClient, spec: CaseSpec, language: Language) -> str:
    raise NotImplementedError
