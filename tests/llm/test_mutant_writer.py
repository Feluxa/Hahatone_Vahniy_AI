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
    _normalize_patch,
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


def test_normalize_patch() -> None:
    # Валидный патч с a/ и b/
    valid = "--- a/file.py\n+++ b/file.py\n@@ -1,1 +1,1 @@\n-old\n+new\n"
    assert _normalize_patch(valid) == valid

    # Патч без a/ и b/ префиксов
    no_prefix = "--- file.py\n+++ file.py\n@@ -1,1 +1,1 @@\n-old\n+new\n"
    norm = _normalize_patch(no_prefix)
    assert norm is not None
    assert "--- a/file.py" in norm
    assert "+++ b/file.py" in norm

    # Патч без @@ (не unified diff)
    assert _normalize_patch("--- a/f\n+++ b/f\n-old\n+new") is None

    # Патч без изменений (+/-)
    assert _normalize_patch("--- a/f\n+++ b/f\n@@ -1 +1 @@\n context") is None


def test_sanitize_name() -> None:
    assert _sanitize_name("boundary-bug", 1) == "llm-mutant-boundary-bug"
    assert _sanitize_name("llm-mutant-already", 1) == "llm-mutant-already"
    assert _sanitize_name("bad name with spaces!", 2) == "llm-mutant-bad-name-with-spaces"


def test_write_mutants_success(sample_context: RepoContext, sample_draft: CaseDraft) -> None:
    mock_client = MagicMock(spec=LlmClient)
    sample_patch = "--- a/NettingPolicy.py\n+++ b/NettingPolicy.py\n@@ -10,3 +10,3 @@\n-net = purchases - refunds\n+net = purchases + refunds\n"
    mutants_data = [
        {
            "name": "sign-inversion",
            "description": "Инвертирован знак вычитания возвратов",
            "patch": sample_patch,
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
    assert m.patch == sample_patch
    assert mock_client.complete.call_args.kwargs["purpose"] == "mutants"


def test_write_mutants_wrapped_in_dict(sample_context: RepoContext, sample_draft: CaseDraft) -> None:
    mock_client = MagicMock(spec=LlmClient)
    sample_patch = "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-1\n+2\n"
    payload = {
        "mutants": [
            {
                "name": "mutant-wrap",
                "description": "Wrapped mutant",
                "patch": sample_patch,
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
    sample_patch = "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-1\n+2\n"
    good_data = [{"name": "repaired", "description": "d", "patch": sample_patch}]

    mock_client.complete.side_effect = [
        LlmResponse(text="Broken JSON", model="GigaChat-3-Ultra", input_tokens=300, output_tokens=20, duration_sec=0.5),
        LlmResponse(text=json.dumps(good_data), model="GigaChat-3-Ultra", input_tokens=350, output_tokens=50, duration_sec=0.5),
    ]

    mutants = write_mutants(mock_client, sample_context, sample_draft, "")
    assert len(mutants) == 1
    assert mutants[0].name == "llm-mutant-repaired"
    assert mock_client.complete.call_count == 2
    assert mock_client.complete.call_args_list[1].kwargs["purpose"] == "mutants:repair"

