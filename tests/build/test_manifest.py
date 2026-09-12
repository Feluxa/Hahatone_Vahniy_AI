"""task.toml: генерация и обратное чтение списков (PROTOCOL.md, раздел 4).

Образец формата — materials/hackathon-participants/example-case/task.toml, и рендер обязан
совпадать с ним дословно: манифест читают чужие инструменты, а не только наш харнесс.

Строки экранируются честно: в описании и в имени автора встречаются кавычки, обратные слеши
и кириллица, а порченый TOML сломает приёмку кейса целиком.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from harness.build.manifest import ManifestError, read_test_lists, render_task_toml
from harness.contracts import (
    TASK_SCHEMA_VERSION, Author, CaseInput, CaseSpec, Difficulty, Language, Limits, TestLists,
)

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "materials" / "hackathon-participants" / "example-case" / "task.toml"
needs_example = pytest.mark.skipif(not EXAMPLE.is_file(), reason="materials/ не выложены локально")


def make_case(**changes: object) -> CaseInput:
    fields: dict[str, object] = {
        "protocol_version": "1.0",
        "repository": Path("/tmp/repo"),
        "brief": "бриф",
        "output_dir": Path("/tmp/out"),
        "case_id": "example/half-open-interval",
        "difficulty": Difficulty.EASY,
        "language": Language.RU,
        "source": "example/interval",
        "team": "team-example",
        "author": Author(name="Участник Примеров", email="participant@example.org"),
        "limits": Limits(agent_timeout_sec=600, verifier_timeout_sec=60, build_timeout_sec=600,
                         cpus=1, memory_mb=1024, storage_mb=2048),
        "seed": 4107,
    }
    fields.update(changes)
    return CaseInput(**fields)  # type: ignore[arg-type]


def make_spec(**changes: object) -> CaseSpec:
    fields: dict[str, object] = {
        "goal": "цель",
        "behavior": ["поведение"],
        "invariants": ["инвариант"],
        "edge_cases": ["граница"],
        "defect_hypothesis": "гипотеза",
        "bank_domain": "Общие программные утилиты",
        "description": "Исправление проверки принадлежности полуоткрытому интервалу",
    }
    fields.update(changes)
    return CaseSpec(**fields)  # type: ignore[arg-type]


EXAMPLE_LISTS = TestLists(
    fail_to_pass=[
        "tests/test_interval.py::test_right_boundary",
        "tests/test_interval.py::test_empty_interval",
    ],
    pass_to_pass=[
        "tests/test_interval.py::test_existing_membership_and_api",
        "tests/test_interval.py::test_invalid_bounds",
    ],
    anti_cheat=["tests/test_interval.py::test_legacy_unchanged"],
)


def render(**changes: object) -> str:
    case = changes.pop("case", None) or make_case()
    spec = changes.pop("spec", None) or make_spec()
    lists = changes.pop("lists", None) or EXAMPLE_LISTS
    return render_task_toml(case, spec, lists)  # type: ignore[arg-type]


def parse(text: str) -> dict[str, object]:
    return tomllib.loads(text)


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "task.toml"
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Формат
# ---------------------------------------------------------------------------

@needs_example
def test_render_repeats_the_example_case_byte_for_byte() -> None:
    expected = EXAMPLE.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert render() == expected


def test_required_sections_and_constants() -> None:
    data = parse(render())
    assert data["schema_version"] == TASK_SCHEMA_VERSION
    assert data["task"]["name"] == "example/half-open-interval"
    assert data["task"]["authors"] == [
        {"name": "Участник Примеров", "email": "participant@example.org"},
    ]
    assert data["metadata"]["task_type"] == "agentic"
    assert data["metadata"]["build_tool"] == "docker"
    assert data["metadata"]["language"] == "ru"
    assert data["metadata"]["difficulty"] == "easy"
    assert data["metadata"]["bank_domain"] == "Общие программные утилиты"
    assert data["agent"]["timeout_sec"] == 600
    assert data["verifier"]["timeout_sec"] == 60
    assert data["environment"] == {
        "allow_internet": False, "build_timeout_sec": 600, "cpus": 1,
        "memory_mb": 1024, "storage_mb": 2048,
    }


def test_internet_is_always_forbidden() -> None:
    case = make_case(limits=Limits(agent_timeout_sec=1, verifier_timeout_sec=1,
                                   build_timeout_sec=1, cpus=4, memory_mb=1, storage_mb=1))
    assert parse(render(case=case))["environment"]["allow_internet"] is False


@pytest.mark.parametrize(("cpus", "rendered"), [(2, "cpus = 2"), (2.0, "cpus = 2"),
                                                (1.5, "cpus = 1.5"), (0.5, "cpus = 0.5")])
def test_cpus_keeps_the_shape_of_the_example(cpus: float, rendered: str) -> None:
    """В образце cpus — целое, поэтому целое значение не должно превращаться в 2.0."""
    case = make_case(limits=Limits(agent_timeout_sec=600, verifier_timeout_sec=60,
                                   build_timeout_sec=600, cpus=cpus, memory_mb=1, storage_mb=1))
    assert rendered in render(case=case)


# ---------------------------------------------------------------------------
# Экранирование
# ---------------------------------------------------------------------------

TRICKY = 'Кавычка ", слеш \\, путь C:\\Users\\Ульяна и ёлка'


def test_quotes_backslashes_and_cyrillic_survive_round_trip() -> None:
    spec = make_spec(description=TRICKY, bank_domain='Домен с "кавычками"')
    case = make_case(author=Author(name='Участник "Примеров" \\ №1', email="a@b.c"))
    data = parse(render(case=case, spec=spec))
    assert data["task"]["description"] == TRICKY
    assert data["metadata"]["bank_domain"] == 'Домен с "кавычками"'
    assert data["task"]["authors"][0]["name"] == 'Участник "Примеров" \\ №1'


def test_escaping_is_written_out_and_not_left_raw() -> None:
    text = render(spec=make_spec(description='один " и один \\'))
    assert 'description = "один \\" и один \\\\"' in text


def test_control_characters_are_escaped() -> None:
    spec = make_spec(description="строка\nс переводом\tи табом\x01")
    text = render(spec=spec)
    assert "\ndescription = " in text
    assert text.count("\ndescription = ") == 1  # значение не разорвано на две строки
    assert parse(text)["task"]["description"] == "строка\nс переводом\tи табом\x01"


def test_cyrillic_test_ids_survive(tmp_path: Path) -> None:
    lists = TestLists(fail_to_pass=["tests/test_чек.py::test_возврат[ключ-\"1\"]"],
                      pass_to_pass=[], anti_cheat=[])
    assert read_test_lists(write(tmp_path, render(lists=lists))) == lists


# ---------------------------------------------------------------------------
# Обратное чтение
# ---------------------------------------------------------------------------

def test_round_trip_returns_the_same_lists(tmp_path: Path) -> None:
    assert read_test_lists(write(tmp_path, render())) == EXAMPLE_LISTS


@needs_example
def test_read_test_lists_reads_the_example_case() -> None:
    assert read_test_lists(EXAMPLE) == EXAMPLE_LISTS


def test_empty_optional_lists_survive_round_trip(tmp_path: Path) -> None:
    lists = TestLists(fail_to_pass=["tests/t.py::a"], pass_to_pass=[], anti_cheat=[])
    text = render(lists=lists)
    assert "pass_to_pass = []" in text
    assert read_test_lists(write(tmp_path, text)) == lists


def test_missing_file_is_a_manifest_error(tmp_path: Path) -> None:
    with pytest.raises(ManifestError):
        read_test_lists(tmp_path / "absent.toml")


@pytest.mark.parametrize("content", [
    b"not a toml at all = = =",
    b"[task]\nname = \"x\"\n",
    b"[metadata]\nfail_to_pass = \"tests/t.py::a\"\npass_to_pass = []\nanti_cheat = []\n",
    b"[metadata]\nfail_to_pass = [1]\npass_to_pass = []\nanti_cheat = []\n",
])
def test_broken_manifest_is_rejected(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "task.toml"
    path.write_bytes(content)
    with pytest.raises(ManifestError):
        read_test_lists(path)


def test_reading_checks_the_same_rules_as_writing(tmp_path: Path) -> None:
    path = tmp_path / "task.toml"
    path.write_text('[metadata]\nfail_to_pass = ["tests/t.py"]\npass_to_pass = []\n'
                    'anti_cheat = []\n', encoding="utf-8")
    with pytest.raises(ManifestError, match="::"):
        read_test_lists(path)


# ---------------------------------------------------------------------------
# Проверка списков
# ---------------------------------------------------------------------------

def test_empty_fail_to_pass_is_rejected() -> None:
    lists = TestLists(fail_to_pass=[], pass_to_pass=["tests/t.py::a"], anti_cheat=[])
    with pytest.raises(ManifestError, match="fail_to_pass"):
        render(lists=lists)


def test_same_id_in_two_lists_is_rejected() -> None:
    lists = TestLists(fail_to_pass=["tests/t.py::a"], pass_to_pass=["tests/t.py::a"], anti_cheat=[])
    with pytest.raises(ManifestError, match="tests/t.py::a"):
        render(lists=lists)


def test_same_id_twice_in_one_list_is_rejected() -> None:
    lists = TestLists(fail_to_pass=["tests/t.py::a", "tests/t.py::a"], pass_to_pass=[],
                      anti_cheat=[])
    with pytest.raises(ManifestError, match="tests/t.py::a"):
        render(lists=lists)


@pytest.mark.parametrize("test_id", ["tests/test_interval.py", "test_right_boundary", "", "   "])
def test_id_without_separator_is_rejected(test_id: str) -> None:
    lists = TestLists(fail_to_pass=[test_id], pass_to_pass=[], anti_cheat=[])
    with pytest.raises(ManifestError):
        render(lists=lists)


def test_all_problems_are_collected_at_once() -> None:
    lists = TestLists(fail_to_pass=[], pass_to_pass=["tests/t.py::a", "no-separator"],
                      anti_cheat=["tests/t.py::a"])
    with pytest.raises(ManifestError) as failure:
        render(lists=lists)
    problems = "\n".join(failure.value.problems)
    assert len(failure.value.problems) == 3
    assert "fail_to_pass" in problems
    assert "no-separator" in problems
    assert "tests/t.py::a" in problems
