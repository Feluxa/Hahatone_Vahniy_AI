"""Тесты для harness/llm/repair.py."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

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
from harness.llm.parsing import ParsingError
from harness.llm.repair import create_case_draft, repair
from harness.llm.test_writer import lists_inconsistent_with_files


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



def _tests_verdict() -> Verdict:
    return Verdict(
        ok=False,
        problems=[
            Problem(
                category=ProblemCategory.BASE_F2P_PASSED,
                target=RepairTarget.TESTS,
                details="fail_to_pass прошёл на базовом коде",
                test_ids=["tests/test_settlement.py::test_initial"],
            )
        ],
        runs=["base/fail_to_pass"],
    )


def _client_returning(payload: dict) -> MagicMock:
    client = MagicMock(spec=LlmClient)
    client.complete.return_value = LlmResponse(
        text=json.dumps(payload),
        model="GigaChat-3-Ultra",
        input_tokens=400,
        output_tokens=100,
        duration_sec=1.0,
    )
    return client


def test_repair_realigns_lists_to_returned_file(
    sample_context: RepoContext, sample_draft: CaseDraft,
) -> None:
    """Модель вернула файл под новым именем, а списки — со старым: черновик обязан сойтись.

    Раньше такой черновик доезжал до write_task_folder и ронял весь прогон
    с «списки тестов ссылаются на файл, которого нет в черновике».
    """
    client = _client_returning({
        "test_file_name": "test_renamed.py",
        "test_file_content": "def test_repaired_f2p():\n    assert False\n",
        "fail_to_pass": ["tests/test_settlement_close.py::test_repaired_f2p"],
        "pass_to_pass": [],
        "anti_cheat": [],
    })

    repaired = repair(client, sample_context, sample_draft, _tests_verdict(), {})

    assert set(repaired.test_files) == {"test_renamed.py"}
    assert repaired.lists.fail_to_pass == ["tests/test_renamed.py::test_repaired_f2p"]
    assert lists_inconsistent_with_files(repaired.test_files, repaired.lists) == []


def test_repair_keeps_previous_draft_when_lists_cannot_be_aligned(
    sample_context: RepoContext, sample_draft: CaseDraft,
) -> None:
    """Ни один ID не привязался к возвращённому файлу — итерация ремонта провалена."""
    client = _client_returning({
        "test_file_name": "test_renamed.py",
        "test_file_content": "def test_only_guard():\n    assert True\n",
        "fail_to_pass": ["tests/test_settlement_close.py::test_vanished"],
        "pass_to_pass": [],
        "anti_cheat": [],
    })

    repaired = repair(client, sample_context, sample_draft, _tests_verdict(), {})

    # Прежний рабочий набор сохранён, исключение наверх не ушло.
    assert repaired.test_files == sample_draft.test_files
    assert repaired.lists == sample_draft.lists


def test_create_case_draft_rejects_inconsistent_lists(sample_context: RepoContext) -> None:
    """Несогласованный черновик ловится до записи на диск, а не в write_task_folder."""
    client = MagicMock(spec=LlmClient)

    def _fake_write_tests(_client, _context, _spec):
        return (
            {"test_generated.py": "def test_ok():\n    assert True\n"},
            TestLists(fail_to_pass=[], pass_to_pass=["tests/test_generated.py::test_ok"], anti_cheat=[]),
            [],
        )

    with patch("harness.llm.repair.write_spec") as spec_mock, \
         patch("harness.llm.repair.write_instruction", return_value="# Задание"), \
         patch("harness.llm.repair.write_tests", side_effect=_fake_write_tests), \
         patch("harness.llm.repair.write_solution") as solution_mock:
        spec_mock.return_value = CaseSpec(
            goal="g", behavior=[], invariants=[], edge_cases=[],
            defect_hypothesis="d", bank_domain="Расчеты", description="desc",
        )
        with pytest.raises(ParsingError) as excinfo:
            create_case_draft(client, sample_context)

    assert "fail_to_pass" in str(excinfo.value)
    solution_mock.assert_not_called()


def test_repair_moves_test_from_pass_to_pass_into_fail_to_pass(sample_context: RepoContext) -> None:
    """Тест ловит дефект, но лежит в pass_to_pass — ремонт обязан перенести его в fail_to_pass.

    Живой прогон: test_boundary_midnight_exclusive_end ждал net = -5, база давала +5,
    и кейс не мог стать валидным, пока тест числился защитным.
    """
    code = (
        "def test_boundary_midnight_exclusive_end():\n    assert net() == -5\n\n"
        "def test_preview_regular():\n    assert True\n"
    )
    draft = CaseDraft(
        spec=CaseSpec(
            goal="g", behavior=[], invariants=[], edge_cases=[],
            defect_hypothesis="d", bank_domain="Расчеты", description="desc",
        ),
        instruction_md="# Задание",
        test_files={"test_settlement.py": code},
        lists=TestLists(
            fail_to_pass=["tests/test_settlement.py::test_preview_regular"],
            pass_to_pass=["tests/test_settlement.py::test_boundary_midnight_exclusive_end"],
            anti_cheat=[],
        ),
        solution_files={"solve.sh": "#!/bin/sh\n"},
    )
    verdict = Verdict(
        ok=False,
        problems=[Problem(
            category=ProblemCategory.BASE_GUARD_FAILED,
            target=RepairTarget.TESTS,
            details="Guard test упал на базовом коде: ожидалось -5, получено 5",
            test_ids=["tests/test_settlement.py::test_boundary_midnight_exclusive_end"],
        )],
        runs=["base/pass_to_pass"],
    )
    # Модель переклассифицировала тест, содержимое файла не трогая.
    client = _client_returning({
        "test_file_name": "test_settlement.py",
        "test_file_content": code,
        "fail_to_pass": ["tests/test_settlement.py::test_boundary_midnight_exclusive_end"],
        "pass_to_pass": ["tests/test_settlement.py::test_preview_regular"],
        "anti_cheat": [],
    })

    repaired = repair(client, sample_context, draft, verdict, {})

    assert repaired.lists.fail_to_pass == [
        "tests/test_settlement.py::test_boundary_midnight_exclusive_end",
    ]
    assert repaired.lists.pass_to_pass == ["tests/test_settlement.py::test_preview_regular"]
    assert repaired.lists.duplicates() == []
    # Сам тест не переписан: ошибочна была классификация, а не тест.
    assert repaired.test_files["test_settlement.py"] == code.strip()


def test_repair_move_applies_when_model_returns_only_new_list(sample_context: RepoContext) -> None:
    """Модель вернула только fail_to_pass — тест всё равно уходит из pass_to_pass."""
    code = "def test_boundary():\n    assert net() == -5\n\ndef test_other():\n    assert True\n"
    draft = CaseDraft(
        spec=CaseSpec(
            goal="g", behavior=[], invariants=[], edge_cases=[],
            defect_hypothesis="d", bank_domain="Расчеты", description="desc",
        ),
        instruction_md="# Задание",
        test_files={"test_settlement.py": code},
        lists=TestLists(
            fail_to_pass=["tests/test_settlement.py::test_other"],
            pass_to_pass=["tests/test_settlement.py::test_boundary"],
            anti_cheat=[],
        ),
        solution_files={"solve.sh": "#!/bin/sh\n"},
    )
    verdict = Verdict(
        ok=False,
        problems=[Problem(
            category=ProblemCategory.BASE_GUARD_FAILED,
            target=RepairTarget.TESTS,
            details="Guard test упал на базовом коде",
        )],
        runs=["base/pass_to_pass"],
    )
    client = _client_returning({
        "test_file_name": "test_settlement.py",
        "test_file_content": code,
        "fail_to_pass": [
            "tests/test_settlement.py::test_other",
            "tests/test_settlement.py::test_boundary",
        ],
    })

    repaired = repair(client, sample_context, draft, verdict, {})

    assert "tests/test_settlement.py::test_boundary" in repaired.lists.fail_to_pass
    assert "tests/test_settlement.py::test_boundary" not in repaired.lists.pass_to_pass
    assert repaired.lists.duplicates() == []


def test_repair_prompt_explains_when_to_move_and_when_to_fix() -> None:
    prompt = (Path(__file__).resolve().parents[2] / "harness" / "llm" / "prompts" / "repair.md").read_text(
        encoding="utf-8"
    )

    assert "ПЕРЕНЕСИ его в `fail_to_pass`" in prompt
    assert "ПОЧИНИ тест" in prompt


_BROKEN_ASYNC = (
    "def test_close() -> None:\n"
    "    async with container() as scope:\n"
    "        assert True\n"
)


def test_create_case_draft_rejects_uncompilable_tests(sample_context: RepoContext) -> None:
    """Файл с SyntaxError не доходит до write_task_folder и до Docker."""
    client = MagicMock(spec=LlmClient)

    def _fake_write_tests(_client, _context, _spec):
        return (
            {"test_case.py": _BROKEN_ASYNC},
            TestLists(fail_to_pass=["tests/test_case.py::test_close"], pass_to_pass=[], anti_cheat=[]),
            [],
        )

    with patch("harness.llm.repair.write_spec") as spec_mock, \
         patch("harness.llm.repair.write_instruction", return_value="# Задание"), \
         patch("harness.llm.repair.write_tests", side_effect=_fake_write_tests), \
         patch("harness.llm.repair.write_solution") as solution_mock:
        spec_mock.return_value = CaseSpec(
            goal="g", behavior=[], invariants=[], edge_cases=[],
            defect_hypothesis="d", bank_domain="Расчеты", description="desc",
        )
        with pytest.raises(ParsingError) as excinfo:
            create_case_draft(client, sample_context)

    message = str(excinfo.value)
    assert "не компилируются" in message
    assert "test_case.py:2" in message
    assert "'async with' outside async function" in message
    # До сборки решения и папки кейса дело не дошло.
    solution_mock.assert_not_called()


def test_repair_with_uncompilable_tests_is_a_failed_iteration(
    sample_context: RepoContext, sample_draft: CaseDraft,
) -> None:
    """Ремонт вернул нерабочий файл — итерация неудачная, прежние тесты сохранены."""
    client = _client_returning({
        "test_file_name": "test_case.py",
        "test_file_content": _BROKEN_ASYNC,
        "fail_to_pass": ["tests/test_case.py::test_close"],
        "pass_to_pass": [],
        "anti_cheat": [],
    })

    repaired = repair(client, sample_context, sample_draft, _tests_verdict(), {})

    assert repaired.test_files == sample_draft.test_files
    assert repaired.lists == sample_draft.lists


def test_repair_does_not_touch_solution_when_only_tests_are_broken(
    sample_context: RepoContext, sample_draft: CaseDraft,
) -> None:
    """Диагноз test_invalid ведёт в тесты; solve.sh на такой итерации не переписывается."""
    verdict = Verdict(
        ok=False,
        problems=[Problem(
            category=ProblemCategory.TEST_INVALID,
            target=RepairTarget.TESTS,
            details="Тест падает одинаково на исходном коде и на эталоне: ValidationError",
            test_ids=["tests/test_settlement.py::test_initial"],
        )],
        runs=["base/full", "oracle/full"],
    )
    client = _client_returning({
        "test_file_name": "test_settlement.py",
        "test_file_content": "def test_initial():\n    assert False\n",
        "fail_to_pass": ["tests/test_settlement.py::test_initial"],
        "pass_to_pass": [],
        "anti_cheat": [],
    })

    repaired = repair(client, sample_context, sample_draft, verdict, {})

    assert repaired.solution_files == sample_draft.solution_files
    assert repaired.instruction_md == sample_draft.instruction_md
    assert "def test_initial" in repaired.test_files["test_settlement.py"]
    # Ровно один вызов модели — только ремонт тестов.
    assert client.complete.call_count == 1
    assert client.complete.call_args.kwargs["purpose"] == "repair:tests"


def test_repair_prompt_explains_test_invalid() -> None:
    prompt = (Path(__file__).resolve().parents[2] / "harness" / "llm" / "prompts" / "repair.md").read_text(
        encoding="utf-8"
    )

    assert "test_invalid" in prompt
    assert "НЕ ТРОГАЙ solve.sh" in prompt
    assert "pytest.raises" in prompt
