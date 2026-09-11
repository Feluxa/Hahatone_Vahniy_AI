"""Генерация тестов и трёх списков. Владелец: №2. Образец качества: golden/settlement-001."""
from __future__ import annotations

from harness.contracts import CaseSpec, RepoContext, TestLists
from harness.llm.client import LlmClient


def write_tests(client: LlmClient, context: RepoContext, spec: CaseSpec) -> tuple[dict[str, str], TestLists]:
    raise NotImplementedError
