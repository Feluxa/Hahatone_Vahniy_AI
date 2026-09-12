"""Тесты для harness/llm/repair.py."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from harness.contracts import (
    CaseDraft,
    CaseSpec,
    Language,
    Problem,
    ProblemCategory,
    RepairTarget,
    RepoContext,
    RunProfile,
    TestLists,
    Verdict,
)
from harness.llm.client import LlmClient, LlmResponse
from harness.llm.repair import create_case_draft, repair


@pytest.fixture
def sample_draft() -> CaseDraft:
    spec = CaseSpec(
        goal="Устранить расхождение",
        behavior=["Покупки увеличивают net_amount", "Возвраты уменьшают net_amount"],
        invariants=["Схема БД неизменна"],
        edge_cases=["Граница суток"],
        defect_hypothesis="NettingPolicy.py знак сложения вместо вычитания",
        bank_domain="Расчеты",
        description="Согласование",
    )
    return CaseDraft(
        spec=spec,
        instruction_md="# Исходная инструкция",
        test_files={"test_settlement.py": "def test_initial(): assert True"},
        lists=TestLists(fail_to_pass=["tests/test_settlement.py::test_initial"], pass_to_pass=[], anti_cheat=[]),
        solution_files={"solve.sh": "#!/bin/sh\necho initial"},
    )


@pytest.fixture
def sample_context() -> RepoContext:
    return RepoContext(
        snapshot_sha256="sha123",
        brief="Бриф задачи",
        files=[],
        python_symbols=[],
        sql_objects=[],
        existing_tests=[],
        run_profile=RunProfile(python_version="3.11", requirements_file=None),
    )


def test_repair_noop_when_verdict_ok(sample_context: RepoContext, sample_draft: CaseDraft) -> None:
    mock_client = MagicMock(spec=LlmClient)
    verdict = Verdict(ok=True, problems=[], runs=["base/full"])

    repaired = repair(mock_client, sample_context, sample_draft, verdict, {})

    assert repaired == sample_draft
    assert mock_client.complete.call_count == 0


def test_repair_instruction_only(sample_context: RepoContext, sample_draft: CaseDraft) -> None:
    mock_client = MagicMock(spec=LlmClient)
    verdict = Verdict(
        ok=False,
        problems=[
            Problem(
                category=ProblemCategory.INSTRUCTION_LEAK,
                target=RepairTarget.INSTRUCTION,
                details="Найдено имя теста test_initial в инструкции",
            )
        ],
        runs=["base/full"],
    )
    mock_client.complete.return_value = LlmResponse(
        text="# Очищенная инструкция без утечек",
        model="GigaChat-3-Ultra",
        input_tokens=200,
        output_tokens=50,
        duration_sec=0.8,
    )

    repaired = repair(mock_client, sample_context, sample_draft, verdict, {})

    assert repaired.instruction_md == "# Очищенная инструкция без утечек"
    # Решение и тесты должны остаться строго нетронутыми!
    assert repaired.test_files == sample_draft.test_files
    assert repaired.lists == sample_draft.lists
    assert repaired.solution_files == sample_draft.solution_files
    assert mock_client.complete.call_args.kwargs["purpose"] == "repair:instruction"


def test_repair_solution_only(sample_context: RepoContext, sample_draft: CaseDraft) -> None:
    mock_client = MagicMock(spec=LlmClient)
    verdict = Verdict(
        ok=False,
        problems=[
            Problem(
                category=ProblemCategory.ORACLE_FAILED,
                target=RepairTarget.SOLUTION,
                details="Тест test_initial упал после решения",
                test_ids=["tests/test_settlement.py::test_initial"],
            )
        ],
        runs=["oracle/full"],
    )
    solution_json = {
        "modifications": [
            {
                "file_path": "policy.py",
                "anchor": "a + b",
                "replacement": "a - b",
            }
        ]
    }
    mock_client.complete.return_value = LlmResponse(
        text=json.dumps(solution_json),
        model="GigaChat-3-Ultra",
        input_tokens=300,
        output_tokens=100,
        duration_sec=1.0,
    )

    repaired = repair(mock_client, sample_context, sample_draft, verdict, {"pytest.log": "AssertionError: 130 != 70"})

    assert repaired.instruction_md == sample_draft.instruction_md
    assert repaired.test_files == sample_draft.test_files
    assert repaired.lists == sample_draft.lists
    # Решение должно обновиться
    assert "a - b" in repaired.solution_files["solve.sh"]
    assert mock_client.complete.call_args.kwargs["purpose"] == "repair:solution"


def test_repair_tests_only(sample_context: RepoContext, sample_draft: CaseDraft) -> None:
    mock_client = MagicMock(spec=LlmClient)
    verdict = Verdict(
        ok=False,
        problems=[
            Problem(
                category=ProblemCategory.BASE_F2P_PASSED,
                target=RepairTarget.TESTS,
                details="fail_to_pass тест прошел на базовом коде (не поймал дефект)",
                test_ids=["tests/test_settlement.py::test_initial"],
            )
        ],
        runs=["base/fail_to_pass"],
    )
    tests_json = {
        "test_file_name": "test_settlement.py",
        "test_file_content": "def test_repaired_f2p(): assert False",
        "fail_to_pass": ["tests/test_settlement.py::test_repaired_f2p"],
        "pass_to_pass": [],
        "anti_cheat": [],
    }
    mock_client.complete.return_value = LlmResponse(
        text=json.dumps(tests_json),
        model="GigaChat-3-Ultra",
        input_tokens=400,
        output_tokens=100,
        duration_sec=1.0,
    )

    repaired = repair(mock_client, sample_context, sample_draft, verdict, {})

    assert repaired.instruction_md == sample_draft.instruction_md
    assert repaired.solution_files == sample_draft.solution_files
    # Тесты должны обновиться
    assert "def test_repaired_f2p" in repaired.test_files["test_settlement.py"]
    assert repaired.lists.fail_to_pass == ["tests/test_settlement.py::test_repaired_f2p"]
    assert mock_client.complete.call_args.kwargs["purpose"] == "repair:tests"


def test_create_case_draft_end_to_end(sample_context: RepoContext) -> None:
    mock_client = MagicMock(spec=LlmClient)
    spec_json = {
        "goal": "Цель кейса",
        "behavior": ["Поведение 1"],
        "invariants": ["Инвариант 1"],
        "edge_cases": ["Край 1"],
        "defect_hypothesis": "Баг в коде",
        "bank_domain": "Банк",
        "description": "Описание",
    }
    instruction_text = "# Задание\nСделайте правильно.\n## Ограничения\nИнвариант 1"
    tests_json = {
        "test_file_name": "test_settlement.py",
        "test_file_content": "def test_f(): assert True",
        "fail_to_pass": ["test_f"],
        "pass_to_pass": [],
        "anti_cheat": [],
    }
    solution_json = {
        "modifications": [
            {"file_path": "a.py", "anchor": "1", "replacement": "2"}
        ]
    }

    mock_client.complete.side_effect = [
        LlmResponse(text=json.dumps(spec_json), model="GigaChat-3-Ultra", input_tokens=100, output_tokens=50, duration_sec=0.5),
        LlmResponse(text=instruction_text, model="GigaChat-3-Ultra", input_tokens=150, output_tokens=50, duration_sec=0.5),
        LlmResponse(text=json.dumps(tests_json), model="GigaChat-3-Ultra", input_tokens=200, output_tokens=50, duration_sec=0.5),
        LlmResponse(text=json.dumps(solution_json), model="GigaChat-3-Ultra", input_tokens=250, output_tokens=50, duration_sec=0.5),
    ]

    draft = create_case_draft(mock_client, sample_context, Language.RU)

    assert isinstance(draft, CaseDraft)
    assert draft.spec.goal == "Цель кейса"
    assert "Задание" in draft.instruction_md
    assert "test_settlement.py" in draft.test_files
    assert draft.lists.fail_to_pass == ["tests/test_settlement.py::test_f"]
    assert "solve.sh" in draft.solution_files
    assert mock_client.complete.call_count == 4

