"""Контракты и фикстуры должны оставаться совместимыми. Если тест упал после правки contracts.py —
обновите фикстуры в том же коммите и напишите в чат."""

import json
from pathlib import Path

import pytest

from harness.contracts import (
    CaseDraft, CaseInput, CaseResult, RepoContext, RunResult, TestLists, UsageLog, Verdict,
)
from harness.serde import from_dict, to_dict

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

SINGLE = {
    "case_input.example.json": CaseInput,
    "repo_context.example.json": RepoContext,
    "case_draft.example.json": CaseDraft,
    "verdict.example.json": Verdict,
    "llm_usage.example.json": UsageLog,
    "result.example.json": CaseResult,
}


@pytest.mark.parametrize("name", sorted(SINGLE))
def test_fixture_roundtrip(name: str) -> None:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    obj = from_dict(SINGLE[name], data)
    assert to_dict(obj) == data


def test_runs_fixture_roundtrip() -> None:
    data = json.loads((FIXTURES / "runs.example.json").read_text(encoding="utf-8"))
    runs = [from_dict(RunResult, item) for item in data["runs"]]
    assert [to_dict(run) for run in runs] == data["runs"]


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValueError):
        from_dict(TestLists, {"fail_to_pass": [], "pass_to_pass": [], "anti_cheat": [], "extra": []})


def test_wrong_type_is_rejected() -> None:
    with pytest.raises(TypeError):
        from_dict(TestLists, {"fail_to_pass": "not a list", "pass_to_pass": [], "anti_cheat": []})


def test_duplicates_across_lists() -> None:
    lists = TestLists(["t::a", "t::b"], ["t::b"], ["t::c"])
    assert lists.duplicates() == ["t::b"]
