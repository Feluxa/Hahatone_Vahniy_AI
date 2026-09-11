"""Запись result.json (PROTOCOL.md, раздел 2).

result.json — единственный артефакт, по которому судят о запуске, поэтому проверяется и его
содержимое, и то, что при отказе на диске не остаётся полуфабриката.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.contracts import CaseResult, Status
from harness.protocol.output import OutputError, write_result
from harness.serde import load_json

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def ready(**overrides: object) -> CaseResult:
    fields: dict[str, object] = {
        "protocol_version": "1.0",
        "case_id": "hackathon/settlement-001",
        "status": Status.READY,
        "task_path": "task",
        "evidence_path": "evidence",
        "limitations": [],
        "input_snapshot_sha256": "f63dfc6392b934d50c961f11250cc576d1160c27f4beb13628b5a720ffccea50",
    }
    fields.update(overrides)
    return CaseResult(**fields)  # type: ignore[arg-type]


def failed(**overrides: object) -> CaseResult:
    fields: dict[str, object] = {
        "status": Status.FAILED,
        "task_path": None,
        "evidence_path": None,
        "limitations": ["base: fail_to_pass прошёл на исходном коде"],
    }
    fields.update(overrides)
    return ready(**fields)


# ---------------------------------------------------------------------------
# Запись
# ---------------------------------------------------------------------------

def test_writes_result_json(tmp_path: Path) -> None:
    path = write_result(tmp_path, ready())
    assert path == tmp_path / "result.json"
    assert path.is_file()


def test_creates_output_dir_with_parents(tmp_path: Path) -> None:
    """При плохом входе output_dir ещё не создан, а result.json со status=failed написать надо."""
    output_dir = tmp_path / "runs" / "team-example"
    write_result(output_dir, failed())
    assert (output_dir / "result.json").is_file()


def test_content_matches_the_fixture(tmp_path: Path) -> None:
    expected = json.loads((FIXTURES / "result.example.json").read_text(encoding="utf-8"))
    path = write_result(tmp_path, ready(input_snapshot_sha256="0" * 64))
    assert json.loads(path.read_text(encoding="utf-8")) == expected


def test_formatting_matches_the_fixture(tmp_path: Path) -> None:
    """Отступ 2 и перевод строки в конце — как у serde.dump_json и у фикстуры."""
    path = write_result(tmp_path, ready(input_snapshot_sha256="0" * 64))
    assert path.read_text(encoding="utf-8") == (FIXTURES / "result.example.json").read_text(encoding="utf-8")


def test_round_trip_through_serde(tmp_path: Path) -> None:
    result = failed(limitations=["не хватило времени на мутанты", "PostgreSQL 16 недоступен"])
    path = write_result(tmp_path, result)
    assert load_json(CaseResult, path) == result


def test_cyrillic_is_not_escaped(tmp_path: Path) -> None:
    path = write_result(tmp_path, failed(limitations=["дефект не воспроизводится"]))
    assert "дефект не воспроизводится" in path.read_text(encoding="utf-8")
    assert "\\u" not in path.read_text(encoding="utf-8")


def test_rewrite_replaces_previous_result(tmp_path: Path) -> None:
    """Пайплайн пишет failed заранее и заменяет на ready в конце."""
    write_result(tmp_path, failed())
    path = write_result(tmp_path, ready())
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["status"] == "ready"
    assert written["limitations"] == []


def test_no_temporary_files_left_behind(tmp_path: Path) -> None:
    write_result(tmp_path, ready())
    assert [item.name for item in tmp_path.iterdir()] == ["result.json"]


def test_nested_paths_are_allowed(tmp_path: Path) -> None:
    write_result(tmp_path, ready(task_path="case/task", evidence_path="case/evidence"))
    assert json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))["task_path"] == "case/task"


def test_ready_may_carry_limitations(tmp_path: Path) -> None:
    """Протокол разрешает описывать ограничения и при успехе."""
    result = ready(limitations=["мутанты проверены только hunk-revert"])
    assert load_json(CaseResult, write_result(tmp_path, result)) == result


# ---------------------------------------------------------------------------
# Проверки перед записью
# ---------------------------------------------------------------------------

def test_wrong_protocol_version(tmp_path: Path) -> None:
    with pytest.raises(OutputError):
        write_result(tmp_path, ready(protocol_version="2.0"))


def test_empty_case_id(tmp_path: Path) -> None:
    with pytest.raises(OutputError):
        write_result(tmp_path, ready(case_id="   "))


@pytest.mark.parametrize("value", ["/task", "C:\\task", "../task", "task/../..", "task\\inner", ""])
def test_bad_task_path(tmp_path: Path, value: str) -> None:
    """task_path и evidence_path — относительные POSIX-пути от output_dir."""
    with pytest.raises(OutputError):
        write_result(tmp_path, ready(task_path=value))


@pytest.mark.parametrize("value", ["/evidence", "../evidence"])
def test_bad_evidence_path(tmp_path: Path, value: str) -> None:
    with pytest.raises(OutputError):
        write_result(tmp_path, ready(evidence_path=value))


def test_failed_without_reason(tmp_path: Path) -> None:
    """status=failed без limitations не объясняет, что пошло не так."""
    with pytest.raises(OutputError):
        write_result(tmp_path, failed(limitations=[]))


@pytest.mark.parametrize("field", ["task_path", "evidence_path"])
def test_ready_without_artifacts(tmp_path: Path, field: str) -> None:
    with pytest.raises(OutputError):
        write_result(tmp_path, ready(**{field: None}))


@pytest.mark.parametrize("value", [
    "F63DFC6392B934D50C961F11250CC576D1160C27F4BEB13628B5A720FFCCEA50",  # верхний регистр
    "f63dfc6392b934d50c961f11250cc576d1160c27f4beb13628b5a720ffccea5",   # 63 символа
    "f63dfc6392b934d50c961f11250cc576d1160c27f4beb13628b5a720ffccea500",  # 65 символов
    "f63dfc6392b934d50c961f11250cc576d1160c27f4beb13628b5a720ffccea5z",  # не hex
    "",
    "  f63dfc6392b934d50c961f11250cc576d1160c27f4beb13628b5a720ffccea5",
])
def test_bad_snapshot_hash(tmp_path: Path, value: str) -> None:
    with pytest.raises(OutputError):
        write_result(tmp_path, ready(input_snapshot_sha256=value))


def test_snapshot_hash_may_be_null(tmp_path: Path) -> None:
    """Хэш может отсутствовать: например, снимок не успели посчитать до сбоя."""
    result = failed(input_snapshot_sha256=None)
    assert load_json(CaseResult, write_result(tmp_path, result)) == result


def test_empty_limitation_string(tmp_path: Path) -> None:
    with pytest.raises(OutputError):
        write_result(tmp_path, failed(limitations=["  "]))


def test_all_problems_are_reported_at_once(tmp_path: Path) -> None:
    with pytest.raises(OutputError) as info:
        write_result(tmp_path, ready(protocol_version="2.0", task_path="/task", case_id=""))
    assert len(info.value.problems) == 3


def test_nothing_is_written_when_validation_fails(tmp_path: Path) -> None:
    with pytest.raises(OutputError):
        write_result(tmp_path, ready(task_path="/task"))
    assert list(tmp_path.iterdir()) == []


def test_previous_result_survives_a_rejected_write(tmp_path: Path) -> None:
    """Неудачная попытка записи не должна испортить уже лежащий result.json."""
    write_result(tmp_path, failed())
    before = (tmp_path / "result.json").read_text(encoding="utf-8")
    with pytest.raises(OutputError):
        write_result(tmp_path, ready(task_path="../task"))
    assert (tmp_path / "result.json").read_text(encoding="utf-8") == before


def test_failed_keeps_null_paths(tmp_path: Path) -> None:
    written = json.loads(write_result(tmp_path, failed()).read_text(encoding="utf-8"))
    assert written["task_path"] is None
    assert written["evidence_path"] is None
