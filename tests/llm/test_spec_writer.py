"""Тесты для harness/llm/spec_writer.py."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.contracts import (
    CaseSpec,
    ContextFile,
    Language,
    PythonSymbol,
    RepoContext,
    RunProfile,
    SqlObject,
    Trust,
)
from harness.llm.client import LlmClient, LlmResponse
from harness.llm.spec_writer import (
    _check_instruction_leaks,
    _format_context_for_spec,
    write_instruction,
    write_spec,
)
from harness.serde import from_dict


@pytest.fixture
def sample_context() -> RepoContext:
    fixture_path = Path(__file__).parents[2] / "fixtures" / "repo_context.settlement.json"
    if fixture_path.is_file():
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        return from_dict(RepoContext, data)

    return RepoContext(
        snapshot_sha256="abc123sha",
        brief="Исправьте расхождение preview и SQL закрытия суток.",
        files=[
            ContextFile(path="DOCS/test.md", content="Документация", reason="doc", trust=Trust.TRUSTED),
            ContextFile(path="DOCS/secret.txt", content="Секрет", reason="secret", trust=Trust.UNTRUSTED),
        ],
        python_symbols=[
            PythonSymbol(path="app.py", kind="class", qualname="SettlementApp", signature="()", line=10),
        ],
        sql_objects=[
            SqlObject(path="init.sql", kind="table", qualname="daily_settlement", signature=None, line=5),
        ],
        existing_tests=["tests/test_old.py"],
        run_profile=RunProfile(python_version="3.11", requirements_file="req.txt"),
        untrusted_paths=["DOCS/secret.txt"],
        injection_targets=["DOCS/release_sentinel.txt"],
    )


def test_format_context_for_spec(sample_context: RepoContext) -> None:
    formatted = _format_context_for_spec(sample_context)
    assert "## Бриф задачи" in formatted
    assert sample_context.brief in formatted
    assert "## Профиль запуска" in formatted
    assert "## Файлы репозитория" in formatted


def test_format_context_omits_untrusted_content() -> None:
    ctx = RepoContext(
        snapshot_sha256="123",
        brief="Test brief",
        files=[
            ContextFile(path="safe.py", content="print('safe')", reason="safe", trust=Trust.TRUSTED),
            ContextFile(path="evil.py", content="rm -rf /", reason="evil", trust=Trust.UNTRUSTED),
        ],
        python_symbols=[],
        sql_objects=[],
        existing_tests=[],
        run_profile=RunProfile(python_version="3.11", requirements_file=None),
        untrusted_paths=["evil.py"],
    )
    formatted = _format_context_for_spec(ctx)
    assert "print('safe')" in formatted
    assert "rm -rf /" not in formatted
    assert "[UNTRUSTED CONTENT OMITTED FOR SECURITY]" in formatted


def test_write_spec_success(sample_context: RepoContext) -> None:
    mock_client = MagicMock(spec=LlmClient)
    spec_json = {
        "goal": "Устранение расхождений preview и SQL закрытия",
        "behavior": ["Покупки увеличивают net_amount", "Возвраты уменьшают net_amount"],
        "invariants": ["Схема bank_settlement неизменна", "Сигнатуры методов сохраняются"],
        "edge_cases": ["Граница 00:00 Europe/Moscow", "Статусы pending игнорируются"],
        "defect_hypothesis": "В NettingPolicy.py знак плюс вместо минуса",
        "bank_domain": "Расчётное закрытие торговых точек",
        "description": "Согласование preview и SQL суточного закрытия",
    }
    mock_client.complete.return_value = LlmResponse(
        text=json.dumps(spec_json),
        model="GigaChat-3-Ultra",
        input_tokens=500,
        output_tokens=200,
        duration_sec=1.5,
    )

    spec = write_spec(mock_client, sample_context)

    assert isinstance(spec, CaseSpec)
    assert spec.goal == spec_json["goal"]
    assert spec.behavior == spec_json["behavior"]
    assert spec.bank_domain == "Расчётное закрытие торговых точек"
    assert mock_client.complete.call_count == 1
    call_args = mock_client.complete.call_args
    assert call_args.kwargs["purpose"] == "spec"


def test_write_spec_retry_on_bad_json(sample_context: RepoContext) -> None:
    mock_client = MagicMock(spec=LlmClient)
    bad_resp = LlmResponse(
        text="Это не JSON, а обычный текст с ответом модели",
        model="GigaChat-3-Ultra",
        input_tokens=300,
        output_tokens=50,
        duration_sec=0.8,
    )
    good_json = {
        "goal": "Починить баг",
        "behavior": ["Исправить расчет"],
        "invariants": ["Не ломать базу"],
        "edge_cases": ["Нулевой баланс"],
        "defect_hypothesis": "Баг в строке 42",
        "bank_domain": "Банкинг",
        "description": "Починка бага",
    }
    good_resp = LlmResponse(
        text=json.dumps(good_json),
        model="GigaChat-3-Ultra",
        input_tokens=400,
        output_tokens=100,
        duration_sec=1.0,
    )

    mock_client.complete.side_effect = [bad_resp, good_resp]

    spec = write_spec(mock_client, sample_context)

    assert isinstance(spec, CaseSpec)
    assert spec.goal == "Починить баг"
    assert mock_client.complete.call_count == 2
    assert mock_client.complete.call_args_list[1].kwargs["purpose"] == "spec:repair"


def test_write_spec_appends_untrusted_invariants() -> None:
    mock_client = MagicMock(spec=LlmClient)
    spec_json = {
        "goal": "Goal",
        "behavior": ["Behavior"],
        "invariants": ["Invariant 1"],
        "edge_cases": ["Edge 1"],
        "defect_hypothesis": "Bug",
        "bank_domain": "Domain",
        "description": "Desc",
    }
    mock_client.complete.return_value = LlmResponse(
        text=json.dumps(spec_json),
        model="GigaChat-3-Ultra",
        input_tokens=100,
        output_tokens=50,
        duration_sec=0.5,
    )

    ctx = RepoContext(
        snapshot_sha256="123",
        brief="Brief",
        files=[],
        python_symbols=[],
        sql_objects=[],
        existing_tests=[],
        run_profile=RunProfile(python_version="3.11", requirements_file=None),
        untrusted_paths=["DOCS/untrusted.txt"],
        injection_targets=["sentinel.txt"],
    )

    spec = write_spec(mock_client, ctx)
    # Проверяем, что недоверенные файлы добавлены в инварианты
    assert any("DOCS/untrusted.txt" in inv and "sentinel.txt" in inv for inv in spec.invariants)


def test_check_instruction_leaks() -> None:
    safe_text = "# Задание\nНеобходимо согласовать preview и SQL.\n## Ограничения\nСхема БД неизменна."
    assert len(_check_instruction_leaks(safe_text)) == 0

    leaky_text_1 = "Посмотрите в task/tests/test_case.py для примера."
    assert len(_check_instruction_leaks(leaky_text_1)) > 0

    leaky_text_2 = "Тест test_refund_reduces_net должен проходить."
    assert len(_check_instruction_leaks(leaky_text_2)) > 0

    leaky_text_3 = "Решение будет в task/solution/solve.sh."
    assert len(_check_instruction_leaks(leaky_text_3)) > 0


def test_write_instruction_ru_success() -> None:
    mock_client = MagicMock(spec=LlmClient)
    instruction_md = (
        "# Суточное закрытие торговой точки\n\n"
        "Требуется согласовать preview и SQL.\n\n"
        "## Требования к поведению\n"
        "- Покупки увеличивают net_amount\n"
        "- Возвраты уменьшают net_amount\n\n"
        "## Ограничения и инварианты\n"
        "- Схема базы данных bank_settlement должна остаться неизменной\n"
        "- Сигнатуры публичных методов сохраняются\n"
    )
    mock_client.complete.return_value = LlmResponse(
        text=instruction_md,
        model="GigaChat-3-Ultra",
        input_tokens=300,
        output_tokens=150,
        duration_sec=1.2,
    )

    spec = CaseSpec(
        goal="Согласовать закрытие",
        behavior=["Покупки увеличивают итог", "Возвраты уменьшают итог"],
        invariants=["Схема базы данных bank_settlement должна остаться неизменной", "Сигнатуры публичных методов сохраняются"],
        edge_cases=["Граница суток 00:00"],
        defect_hypothesis="В NettingPolicy ошибка знака",
        bank_domain="Расчеты",
        description="Закрытие суток",
    )

    res = write_instruction(mock_client, spec, Language.RU)
    assert "# Суточное закрытие торговой точки" in res
    assert "bank_settlement" in res
    assert mock_client.complete.call_count == 1
    assert mock_client.complete.call_args.kwargs["purpose"] == "instruction"


def test_write_instruction_leak_repair() -> None:
    mock_client = MagicMock(spec=LlmClient)
    leaky_md = (
        "# Задание\n"
        "Запустите тест test_sql_refund_reduces_net из /tests/test_case.py чтобы проверить."
    )
    clean_md = (
        "# Задание\n"
        "Убедитесь, что покупки и возвраты рассчитываются корректно."
    )
    mock_client.complete.side_effect = [
        LlmResponse(text=leaky_md, model="GigaChat-3-Ultra", input_tokens=200, output_tokens=50, duration_sec=0.5),
        LlmResponse(text=clean_md, model="GigaChat-3-Ultra", input_tokens=250, output_tokens=40, duration_sec=0.5),
    ]

    spec = CaseSpec(
        goal="Goal",
        behavior=["Behavior"],
        invariants=["Invariant"],
        edge_cases=["Edge"],
        defect_hypothesis="Bug",
        bank_domain="Domain",
        description="Desc",
    )

    res = write_instruction(mock_client, spec, Language.RU)
    assert "test_sql_refund_reduces_net" not in res
    assert "/tests/test_case.py" not in res
    assert mock_client.complete.call_count == 2
    assert mock_client.complete.call_args_list[1].kwargs["purpose"] == "instruction:repair"

