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
from harness.pytest_ids import canonical_test_id
from harness.llm.test_writer import (
    _align_and_validate_tests,
    _protected_files,
    lists_inconsistent_with_files,
    syntax_problems,
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
    # Нераспределённый test_unassigned_isolation идёт в pass_to_pass: угадывать по имени
    # нельзя, а тест, который ловит дефект, переложит reclassify_by_outcomes по исходам.
    assert lists.pass_to_pass == [
        "tests/test_cases.py::test_p2p_normal",
        "tests/test_cases.py::test_unassigned_isolation",
    ]
    assert lists.anti_cheat == ["tests/test_cases.py::test_anti_cheat_schema"]
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

    files, lists, _protected = write_tests(mock_client, sample_context, sample_spec)

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

    files, lists, _protected = write_tests(mock_client, sample_context, sample_spec)

    assert files["test_cases.py"] == fixed_code
    assert lists.fail_to_pass == ["tests/test_cases.py::test_fixed"]
    assert mock_client.complete.call_count == 2
    assert mock_client.complete.call_args_list[1].kwargs["purpose"] == "tests:repair"



def test_align_remaps_ids_from_stale_filename() -> None:
    """Списки из прошлой итерации ссылаются на старый файл — ID переезжают на актуальный."""
    code = "def test_bug():\n    assert False\n\ndef test_guard():\n    assert True\n"
    files = {"test_repaired.py": code}

    files, lists = _align_and_validate_tests(
        files,
        ["tests/test_settlement_close.py::test_bug"],
        [],
        ["tests/test_settlement_close.py::test_guard"],
    )

    assert lists.fail_to_pass == ["tests/test_repaired.py::test_bug"]
    assert lists.anti_cheat == ["tests/test_repaired.py::test_guard"]
    assert lists_inconsistent_with_files(files, lists) == []


def test_align_drops_ids_without_matching_function() -> None:
    """Тест, которого нет ни в одном файле черновика, отбрасывается, а не доезжает до диска."""
    files = {"test_repaired.py": "def test_bug():\n    assert False\n"}

    files, lists = _align_and_validate_tests(
        files,
        ["tests/test_repaired.py::test_bug"],
        ["tests/test_old.py::test_vanished"],
        [],
    )

    assert "test_vanished" not in " ".join(lists.all_ids())
    assert lists_inconsistent_with_files(files, lists) == []


def test_lists_inconsistent_with_files_reports_missing_file() -> None:
    lists = TestLists(
        fail_to_pass=["tests/test_gone.py::test_bug"],
        pass_to_pass=[],
        anti_cheat=[],
    )

    problems = lists_inconsistent_with_files({"test_here.py": ""}, lists)

    assert any("test_gone.py" in p for p in problems)


def test_lists_inconsistent_with_files_reports_empty_fail_to_pass() -> None:
    lists = TestLists(fail_to_pass=[], pass_to_pass=["tests/test_here.py::test_ok"], anti_cheat=[])

    problems = lists_inconsistent_with_files({"test_here.py": "def test_ok(): ..."}, lists)

    assert any("fail_to_pass" in p for p in problems)


def test_lists_consistent_when_everything_matches() -> None:
    lists = TestLists(
        fail_to_pass=["tests/test_here.py::test_bug"],
        pass_to_pass=[],
        anti_cheat=[],
    )

    assert lists_inconsistent_with_files({"test_here.py": "def test_bug(): ..."}, lists) == []


@pytest.mark.parametrize("file_key", ["test_close.py", "tests/test_close.py"])
@pytest.mark.parametrize("raw_id", ["test_close.py::test_bug", "tests/test_close.py::test_bug"])
def test_align_matches_file_regardless_of_tests_prefix(file_key: str, raw_id: str) -> None:
    """ID с префиксом tests/ и без него находят один и тот же файл черновика."""
    files, lists = _align_and_validate_tests(
        {file_key: "def test_bug():\n    assert False\n"}, [raw_id], [], [],
    )

    assert set(files) == {"test_close.py"}
    assert lists.fail_to_pass == ["tests/test_close.py::test_bug"]
    assert lists_inconsistent_with_files(files, lists) == []


def test_align_always_returns_canonical_ids() -> None:
    """На выходе — только tests/<путь>::<тест>, включая подпапки и нераспределённые функции."""
    code = "def test_bug():\n    assert False\n\ndef test_extra():\n    assert True\n"
    files, lists = _align_and_validate_tests({"tests/sql/test_close.py": code}, ["test_bug"], [], [])

    assert set(files) == {"sql/test_close.py"}
    for test_id in lists.all_ids():
        assert test_id == canonical_test_id(test_id)
        assert test_id.startswith("tests/sql/test_close.py::")
    assert "tests/sql/test_close.py::test_extra" in lists.all_ids()


def test_align_refuses_to_guess_between_same_named_files() -> None:
    """Два файла с одинаковым именем в разных папках — несогласованность, а не выбор первого."""
    code = "def test_bug():\n    assert False\n"
    files = {"sql/test_close.py": code, "api/test_close.py": code}

    files, lists = _align_and_validate_tests(files, ["test_close.py::test_bug"], [], [])

    # Молчаливой привязки к первому файлу не произошло.
    assert "tests/sql/test_close.py::test_bug" not in lists.fail_to_pass
    assert "tests/api/test_close.py::test_bug" not in lists.fail_to_pass

    problems = lists_inconsistent_with_files(files, lists)
    assert any("несколько файлов с именем test_close.py" in p for p in problems)


def test_lists_inconsistent_reports_non_canonical_ids() -> None:
    lists = TestLists(fail_to_pass=["test_close.py::test_bug"], pass_to_pass=[], anti_cheat=[])

    problems = lists_inconsistent_with_files({"test_close.py": "def test_bug(): ..."}, lists)

    assert any("каноническом виде" in p for p in problems)


def test_align_does_not_bind_ids_to_expected_files() -> None:
    """Идентификатор не может указывать на .expected: pytest такой файл не собирает."""
    files = {
        "test_close.py": "def test_sentinel_untouched():\n    assert True\n",
        "release_sentinel.txt.expected": "MERIDIAN_RELEASE_INTEGRITY_SENTINEL_OK\n",
    }

    files, lists = _align_and_validate_tests(files, ["test_sentinel_untouched"], [], [])

    assert set(files) == {"test_close.py", "release_sentinel.txt.expected"}
    assert lists.all_ids() == ["tests/test_close.py::test_sentinel_untouched"]
    assert lists_inconsistent_with_files(files, lists) == []


def _tests_prompt() -> str:
    return (Path(__file__).resolve().parents[2] / "harness" / "llm" / "prompts" / "tests.md").read_text(
        encoding="utf-8"
    )


def test_prompt_gives_async_template_not_just_a_ban() -> None:
    """Запрет без образца модель обходит: убирает async у функции, а async with оставляет."""
    prompt = _tests_prompt()

    assert "async def test_" in prompt
    assert "async def scenario()" in prompt
    assert "asyncio.run(scenario())" in prompt
    assert "`await`, `async with` и `async for` допустимы ТОЛЬКО внутри вложенной" in prompt
    assert "SyntaxError" in prompt


def test_prompt_forbids_generated_hashes_and_untrusted_sources() -> None:
    prompt = _tests_prompt()

    assert ".expected" in prompt
    assert "md5" in prompt
    assert "untrusted_paths" in prompt
    assert "protected_files" in prompt
    assert "tests/expected/" in prompt
    assert "read_bytes()" in prompt


def test_protected_files_collects_paths_only() -> None:
    """Модель называет путь; содержимое эталона копирует харнесс."""
    assert _protected_files({
        "protected_files": ["DOCS/release_sentinel.txt", " sql/090_core_seed.sql ", ""]
    }) == ["DOCS/release_sentinel.txt", "sql/090_core_seed.sql"]


def test_protected_files_deduplicates_and_tolerates_absence() -> None:
    assert _protected_files({"protected_files": ["a.txt", "a.txt"]}) == ["a.txt"]
    assert _protected_files({}) == []
    assert _protected_files({"protected_files": "DOCS/x.txt"}) == []


def test_protected_files_keeps_bad_paths_for_validation() -> None:
    """Плохой путь не выбрасывается молча: его отвергнет write_task_folder и уйдёт в ремонт."""
    assert _protected_files({"protected_files": ["../etc/passwd", "нет-такого.txt"]}) == [
        "../etc/passwd", "нет-такого.txt",
    ]


def test_prompt_names_the_dsn_environment_variable() -> None:
    prompt = _tests_prompt()

    assert "CASE_DSN" in prompt
    assert "CASE_DATABASE_URL" in prompt
    assert "127.0.0.1:5432" in prompt
    assert "psycopg.connect()` без аргументов" in prompt


def test_prompt_forbids_computing_expected_path() -> None:
    """Модель применила with_suffix() и получила ValueError — теперь это прямо запрещено."""
    prompt = _tests_prompt()

    assert "with_suffix" in prompt
    assert "ЗАПРЕЩЁН" in prompt
    assert 'Path(__file__).parent / "expected"' in prompt


def test_prompt_restricts_anti_cheat_to_three_templates() -> None:
    """Модель трижды подряд писала фиктивные проверки — теперь выбор ограничен образцами."""
    prompt = _tests_prompt()

    assert "ТОЛЬКО из трёх образцов" in prompt
    assert "inspect.signature" in prompt
    assert "information_schema.columns" in prompt
    assert "table_schema = '<схема>'" in prompt
    # Пустая выборка из information_schema — не доказательство сохранности схемы.
    assert "выборка пуста" in prompt


def test_prompt_forbids_fake_introspection_checks() -> None:
    prompt = _tests_prompt()

    for forbidden in ("__origin__", "__args__", "FieldInfo", "model_fields", "hasattr"):
        assert forbidden in prompt, forbidden
    assert "ЗАПРЕЩЕНО проверять типы через" in prompt


def test_unassigned_functions_never_guessed_into_fail_to_pass() -> None:
    """Имя теста ничего не решает: раскладку по факту делает reclassify_by_outcomes."""
    code = (
        "def test_refund_boundary():\n    assert True\n\n"
        "def test_sentinel_untouched():\n    assert True\n\n"
        "def test_close_window_isolation():\n    assert True\n"
    )

    files, lists = _align_and_validate_tests(
        {"test_case.py": code}, ["tests/test_case.py::test_refund_boundary"], [], [],
    )

    # Только явно объявленный тест попал в fail_to_pass.
    assert lists.fail_to_pass == ["tests/test_case.py::test_refund_boundary"]
    assert lists.anti_cheat == []
    assert lists.pass_to_pass == [
        "tests/test_case.py::test_sentinel_untouched",
        "tests/test_case.py::test_close_window_isolation",
    ]


_ASYNC_WITH_OUTSIDE = (
    "def test_close() -> None:\n"
    "    async with container() as scope:\n"
    "        assert True\n"
)


def test_syntax_problems_catches_async_with_outside_coroutine() -> None:
    """Реальный случай из прогона: модель убрала async у функции, но оставила async with."""
    problems = syntax_problems({"test_case.py": _ASYNC_WITH_OUTSIDE})

    assert len(problems) == 1
    assert problems[0].startswith("test_case.py:2:")
    assert "'async with' outside async function" in problems[0]


def test_syntax_problems_accepts_the_prompt_template() -> None:
    code = (
        "import asyncio\n\n\n"
        "def test_close() -> None:\n"
        "    async def scenario() -> None:\n"
        "        async with container() as scope:\n"
        "            assert await scope.get(X)\n\n"
        "    asyncio.run(scenario())\n"
    )

    assert syntax_problems({"test_case.py": code}) == []


def test_syntax_problems_reports_plain_syntax_error() -> None:
    problems = syntax_problems({"test_case.py": "def test_broken(:\n    assert True\n"})

    assert len(problems) == 1
    assert problems[0].startswith("test_case.py:1:")


def test_syntax_problems_ignores_non_python_files() -> None:
    assert syntax_problems({"data.expected": "это вообще не питон ("}) == []


def test_syntax_problems_checks_every_file() -> None:
    files = {
        "test_a.py": "def test_ok():\n    assert True\n",
        "test_b.py": _ASYNC_WITH_OUTSIDE,
    }

    problems = syntax_problems(files)

    assert len(problems) == 1
    assert problems[0].startswith("test_b.py:")
