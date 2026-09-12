"""Тесты для harness/llm/mutant_writer.py."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from harness.contracts import (
    CaseDraft,
    CaseSpec,
    Mutant,
    MutantSource,
    RepoContext,
    RunProfile,
    TestLists,
)
from harness.llm.client import LlmClient, LlmResponse
from harness.llm.mutant_writer import (
    _replacement_problem,
    _sanitize_name,
    write_mutants,
)


@pytest.fixture
def sample_draft() -> CaseDraft:
    spec = CaseSpec(
        goal="Устранить расхождение",
        behavior=["Возвраты уменьшают итог"],
        invariants=["Схема БД неизменна"],
        edge_cases=["Граница 00:00"],
        defect_hypothesis="NettingPolicy знак плюс",
        bank_domain="Расчеты",
        description="Согласование",
    )
    return CaseDraft(
        spec=spec,
        instruction_md="# Задание\nУстраните расхождение...",
        test_files={"test_settlement.py": "def test_ok(): pass"},
        lists=TestLists(fail_to_pass=[], pass_to_pass=[], anti_cheat=[]),
        solution_files={"solve.sh": "#!/bin/sh\necho ok"},
    )


@pytest.fixture
def sample_context() -> RepoContext:
    return RepoContext(
        snapshot_sha256="abc",
        brief="Бриф",
        files=[],
        python_symbols=[],
        sql_objects=[],
        existing_tests=[],
        run_profile=RunProfile(python_version="3.11", requirements_file=None),
    )


def test_replacement_problem_accepts_valid_mutant() -> None:
    assert _replacement_problem("sql/061.sql", "a < b", "a <= b") is None


@pytest.mark.parametrize(("file_path", "anchor", "replacement", "expected"), [
    ("", "a", "b", "нет file_path"),
    ("/etc/passwd", "a", "b", "относительным"),
    ("../outside.py", "a", "b", "за пределы"),
    ("sql" + chr(92) + "061.sql", "a", "b", "относительным"),
    ("sql/061.sql", "   ", "b", "пустой anchor"),
    ("sql/061.sql", "same", "same", "совпадает"),
])
def test_replacement_problem_rejects(file_path, anchor, replacement, expected) -> None:
    problem = _replacement_problem(file_path, anchor, replacement)
    assert problem is not None
    assert expected in problem


def test_sanitize_name() -> None:
    assert _sanitize_name("boundary-bug", 1) == "llm-mutant-boundary-bug"
    assert _sanitize_name("llm-mutant-already", 1) == "llm-mutant-already"
    assert _sanitize_name("bad name with spaces!", 2) == "llm-mutant-bad-name-with-spaces"


def test_write_mutants_success(sample_context: RepoContext, sample_draft: CaseDraft) -> None:
    mock_client = MagicMock(spec=LlmClient)
    sample_mutant = {
        "file_path": "NettingPolicy.py",
        "anchor": "net = purchases - refunds",
        "replacement": "net = purchases + refunds",
    }
    mutants_data = [
        {
            "name": "sign-inversion",
            "description": "Инвертирован знак вычитания возвратов",
            **sample_mutant,
        }
    ]
    mock_client.complete.return_value = LlmResponse(
        text=json.dumps(mutants_data),
        model="GigaChat-3-Ultra",
        input_tokens=600,
        output_tokens=200,
        duration_sec=1.5,
    )

    mutants = write_mutants(mock_client, sample_context, sample_draft, "oracle diff string")

    assert len(mutants) == 1
    m = mutants[0]
    assert isinstance(m, Mutant)
    assert m.name == "llm-mutant-sign-inversion"
    assert m.source == MutantSource.LLM
    assert m.description == "Инвертирован знак вычитания возвратов"
    assert m.patch == ""
    assert m.is_replacement is True
    assert m.file_path == "NettingPolicy.py"
    assert m.anchor == "net = purchases - refunds"
    assert m.replacement == "net = purchases + refunds"
    assert mock_client.complete.call_args.kwargs["purpose"] == "mutants"


def test_write_mutants_wrapped_in_dict(sample_context: RepoContext, sample_draft: CaseDraft) -> None:
    mock_client = MagicMock(spec=LlmClient)
    sample_mutant = {"file_path": "app.py", "anchor": "value = 1", "replacement": "value = 2"}
    payload = {
        "mutants": [
            {
                "name": "mutant-wrap",
                "description": "Wrapped mutant",
                **sample_mutant,
            }
        ]
    }
    mock_client.complete.return_value = LlmResponse(
        text=json.dumps(payload),
        model="GigaChat-3-Ultra",
        input_tokens=500,
        output_tokens=150,
        duration_sec=1.0,
    )

    mutants = write_mutants(mock_client, sample_context, sample_draft, "")
    assert len(mutants) == 1
    assert mutants[0].name == "llm-mutant-mutant-wrap"


def test_write_mutants_repair_on_bad_json(sample_context: RepoContext, sample_draft: CaseDraft) -> None:
    mock_client = MagicMock(spec=LlmClient)
    sample_mutant = {"file_path": "app.py", "anchor": "value = 1", "replacement": "value = 2"}
    good_data = [{"name": "repaired", "description": "d", **sample_mutant}]

    mock_client.complete.side_effect = [
        LlmResponse(text="Broken JSON", model="GigaChat-3-Ultra", input_tokens=300, output_tokens=20, duration_sec=0.5),
        LlmResponse(text=json.dumps(good_data), model="GigaChat-3-Ultra", input_tokens=350, output_tokens=50, duration_sec=0.5),
    ]

    mutants = write_mutants(mock_client, sample_context, sample_draft, "")
    assert len(mutants) == 1
    assert mutants[0].name == "llm-mutant-repaired"
    assert mock_client.complete.call_count == 2
    assert mock_client.complete.call_args_list[1].kwargs["purpose"] == "mutants:repair"

