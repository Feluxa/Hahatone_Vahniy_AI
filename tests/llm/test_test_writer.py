"""Тесты для harness/llm/test_writer.py."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.contracts import (
    CaseSpec,
    ContextFile,
    RepoContext,
    RunProfile,
    TestLists,
    Trust,
)
from harness.llm.client import LlmClient, LlmResponse
from harness.llm.test_writer import (
    _align_and_validate_tests,
    _extract_test_functions_from_ast,
    _normalize_test_id,
    write_tests,
)
from harness.serde import from_dict


@pytest.fixture
def sample_spec() -> CaseSpec:
    return CaseSpec(
        goal="Устранить расхождение preview и SQL закрытия суток",
        behavior=[
            "Покупки увеличивают net_amount",
            "Возвраты уменьшают net_amount",
        ],
        invariants=[
            "Схема bank_settlement неизменна",
            "Сигнатуры методов сохраняются",
            "DOCS/release_sentinel.txt остается неизменным",
        ],
        edge_cases=["Стык суток 00:00:00 в Europe/Moscow"],
        defect_hypothesis="В NettingPolicy.py знак сложения вместо вычитания",
        bank_domain="Расчётное закрытие торговых точек",
        description="Согласование preview и SQL суточного закрытия",
    )


@pytest.fixture
def sample_context() -> RepoContext:
    fixture_path = Path(__file__).parents[2] / "fixtures" / "repo_context.settlement.json"
    if fixture_path.is_file():
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        return from_dict(RepoContext, data)

    return RepoContext(
        snapshot_sha256="abc123sha",
        brief="Краткий бриф",
        files=[ContextFile(path="test.py", content="code", reason="r", trust=Trust.TRUSTED)],
        python_symbols=[],
        sql_objects=[],
        existing_tests=[],
        run_profile=RunProfile(python_version="3.11", requirements_file="req.txt"),
    )


def test_extract_test_functions_from_ast() -> None:
    code = """
import pytest

def helper():
    pass

def test_first():
    assert True

async def test_second():
    assert True

class TestSuite:
    def test_method(self):
        pass
"""
    funcs = _extract_test_functions_from_ast(code)
    assert funcs == ["test_first", "test_second"]


def test_normalize_test_id() -> None:
    assert _normalize_test_id("test_foo", "test_bar.py") == "tests/test_bar.py::test_foo"
    assert (
        _normalize_test_id("tests/test_custom.py::test_foo", "test_bar.py")
        == "tests/test_custom.py::test_foo"
    )
    assert (
        _normalize_test_id("  test_settlement.py::test_sql  ", "test_bar.py")
        == "tests/test_settlement.py::test_sql"
    )


def test_align_and_validate_tests_deduplication_and_ast() -> None:
    code = """
def test_f2p_defect():
    assert False

def test_p2p_normal():
    assert True

def test_anti_cheat_schema():
    assert True

def test_unassigned_isolation():
    assert True
"""
    files = {"test_cases.py": code}
    f2p_raw = ["test_f2p_defect", "test_non_existent"]
    p2p_raw = ["test_p2p_normal", "test_f2p_defect"]  # Дубликат f2p
    ac_raw = ["test_anti_cheat_schema"]

    files, lists = _align_and_validate_tests(files, f2p_raw, p2p_raw, ac_raw)

    assert isinstance(lists, TestLists)
    # Несуществующий тест должен быть отфильтрован
    assert "tests/test_cases.py::test_non_existent" not in lists.all_ids()
    # Дубликат должен быть исключен из p2p в пользу f2p
    assert lists.fail_to_pass == ["tests/test_cases.py::test_f2p_defect"]
    assert lists.pass_to_pass == ["tests/test_cases.py::test_p2p_normal"]
    # Нераспределенный test_unassigned_isolation должен попасть в anti_cheat
    assert "tests/test_cases.py::test_anti_cheat_schema" in lists.anti_cheat
    assert "tests/test_cases.py::test_unassigned_isolation" in lists.anti_cheat
    # Проверяем отсутствие дубликатов
    assert len(lists.duplicates()) == 0


def test_write_tests_success(sample_context: RepoContext, sample_spec: CaseSpec) -> None:
    mock_client = MagicMock(spec=LlmClient)
    sample_code = """
def test_sql_refund_reduces_net():
    assert 70 == 100 - 30

def test_preview_regular_close():
    assert True

def test_schema_unchanged():
    assert True
"""
    test_json = {
        "test_file_name": "test_settlement_close.py",
        "test_file_content": sample_code,
        "fail_to_pass": ["tests/test_settlement_close.py::test_sql_refund_reduces_net"],
        "pass_to_pass": ["tests/test_settlement_close.py::test_preview_regular_close"],
        "anti_cheat": ["tests/test_settlement_close.py::test_schema_unchanged"],
    }
    mock_client.complete.return_value = LlmResponse(
        text=json.dumps(test_json),
        model="GigaChat-3-Ultra",
        input_tokens=800,
        output_tokens=300,
        duration_sec=2.0,
    )

    files, lists = write_tests(mock_client, sample_context, sample_spec)

    assert "test_settlement_close.py" in files
    assert sample_code.strip() in files["test_settlement_close.py"]
    assert lists.fail_to_pass == ["tests/test_settlement_close.py::test_sql_refund_reduces_net"]
    assert lists.pass_to_pass == ["tests/test_settlement_close.py::test_preview_regular_close"]
    assert lists.anti_cheat == ["tests/test_settlement_close.py::test_schema_unchanged"]
    assert mock_client.complete.call_args.kwargs["purpose"] == "tests"


def test_write_tests_repair_on_syntax_error(sample_context: RepoContext, sample_spec: CaseSpec) -> None:
    mock_client = MagicMock(spec=LlmClient)
    broken_code = "def test_broken(:\n    assert True"
    fixed_code = "def test_fixed():\n    assert True"

    bad_json = {
        "test_file_name": "test_cases.py",
        "test_file_content": broken_code,
        "fail_to_pass": ["test_broken"],
        "pass_to_pass": [],
        "anti_cheat": [],
    }
    good_json = {
        "test_file_name": "test_cases.py",
        "test_file_content": fixed_code,
        "fail_to_pass": ["test_fixed"],
        "pass_to_pass": [],
        "anti_cheat": [],
    }

    mock_client.complete.side_effect = [
        LlmResponse(text=json.dumps(bad_json), model="GigaChat-3-Ultra", input_tokens=500, output_tokens=100, duration_sec=1.0),
        LlmResponse(text=json.dumps(good_json), model="GigaChat-3-Ultra", input_tokens=600, output_tokens=100, duration_sec=1.0),
    ]

    files, lists = write_tests(mock_client, sample_context, sample_spec)

    assert files["test_cases.py"] == fixed_code
    assert lists.fail_to_pass == ["tests/test_cases.py::test_fixed"]
    assert mock_client.complete.call_count == 2
    assert mock_client.complete.call_args_list[1].kwargs["purpose"] == "tests:repair"

