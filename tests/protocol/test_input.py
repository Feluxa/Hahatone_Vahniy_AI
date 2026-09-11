"""Чтение и валидация входного JSON (PROTOCOL.md, раздел 1).

Ключевое требование: сообщать сразу все найденные проблемы, а не первую — иначе исправление
плохого входа превращается в перебор по одной ошибке за запуск.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

from harness.contracts import Difficulty, Language
from harness.protocol.input import InputError, load_input
from tests.protocol.case_input import MISSING, base_input, limits, write_input

MATERIALS = Path(__file__).resolve().parents[2] / "materials" / "hackathon-participants"


def problems_of(path: Path) -> list[str]:
    with pytest.raises(InputError) as info:
        load_input(path)
    return info.value.problems


def only_problem(path: Path, field: str) -> str:
    """Единственная проблема, и она про нужное поле."""
    found = problems_of(path)
    assert len(found) == 1, found
    assert found[0].startswith(field), found[0]
    return found[0]


# ---------------------------------------------------------------------------
# Разбор корректного входа
# ---------------------------------------------------------------------------

def test_parses_every_field(tmp_path: Path) -> None:
    case = load_input(write_input(tmp_path))
    assert case.protocol_version == "1.0"
    assert case.brief.startswith("Устраните расхождение")
    assert case.case_id == "hackathon/settlement-001"
    assert case.difficulty is Difficulty.MEDIUM
    assert case.language is Language.RU
    assert case.source == "hackathon/settlement-001"
    assert case.team == "team-example"
    assert case.author.name == "Участник Примеров"
    assert case.author.email == "participant@example.org"
    assert case.seed == 4107


def test_limits_are_parsed(tmp_path: Path) -> None:
    parsed = load_input(write_input(tmp_path)).limits
    assert parsed.agent_timeout_sec == 1800
    assert parsed.verifier_timeout_sec == 300
    assert parsed.build_timeout_sec == 900
    assert parsed.cpus == 2.0
    assert parsed.memory_mb == 4096
    assert parsed.storage_mb == 10240


def test_paths_are_absolute_and_resolved_against_the_json(tmp_path: Path) -> None:
    case = load_input(write_input(tmp_path))
    assert case.repository == tmp_path / "meridian"
    assert case.output_dir == tmp_path / "runs" / "case"
    assert case.input_path == tmp_path / "inputs" / "case.json"


def test_paths_do_not_depend_on_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Относительные пути считаются от папки входного JSON, а не от текущей директории."""
    path = write_input(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    case = load_input(path)
    assert case.repository == tmp_path / "meridian"


def test_absolute_paths_in_json_are_kept(tmp_path: Path) -> None:
    repository = tmp_path / "meridian"
    case = load_input(write_input(tmp_path, repository=str(repository)))
    assert case.repository == repository


def test_relative_input_path_is_made_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_input(tmp_path)
    monkeypatch.chdir(tmp_path)
    case = load_input(Path("inputs") / "case.json")
    assert case.input_path == tmp_path / "inputs" / "case.json"
    assert case.repository == tmp_path / "meridian"


def test_unknown_fields_are_ignored(tmp_path: Path) -> None:
    """Протокол требует наличия своих полей, но не запрещает чужие: расширение входа нас не ломает."""
    case = load_input(write_input(tmp_path, future_field={"any": 1}))
    assert case.case_id == "hackathon/settlement-001"


def test_unknown_top_level_fields_are_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Опечатка в имени поля не должна проходить совсем незамеченной."""
    with caplog.at_level(logging.WARNING):
        load_input(write_input(tmp_path, future_field=1, случайное=2))
    assert "future_field" in caplog.text
    assert "случайное" in caplog.text


def test_unknown_author_and_limits_fields_are_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        load_input(write_input(
            tmp_path,
            author={"name": "Имя", "email": "a@b.c", "github": "octocat"},
            limits=limits(gpus=1),
        ))
    assert "github" in caplog.text
    assert "gpus" in caplog.text


def test_known_fields_are_not_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        load_input(write_input(tmp_path))
    assert caplog.text == ""


def test_byte_order_mark_does_not_break_parsing(tmp_path: Path) -> None:
    case = load_input(write_input(tmp_path, encoding="utf-8-sig"))
    assert case.team == "team-example"


def test_output_dir_may_be_missing_entirely(tmp_path: Path) -> None:
    """Родителя output_dir тоже может не быть — его создаст write_result."""
    case = load_input(write_input(tmp_path, output_dir="../нет/такой/папки"))
    assert not case.output_dir.exists()


# ---------------------------------------------------------------------------
# Файл целиком
# ---------------------------------------------------------------------------

def test_missing_file(tmp_path: Path) -> None:
    assert len(problems_of(tmp_path / "нет.json")) == 1


def test_directory_instead_of_file(tmp_path: Path) -> None:
    assert len(problems_of(tmp_path)) == 1


def test_broken_json(tmp_path: Path) -> None:
    path = tmp_path / "case.json"
    path.write_text("{ не json", encoding="utf-8")
    assert len(problems_of(path)) == 1


def test_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "case.json"
    path.write_text("", encoding="utf-8")
    assert len(problems_of(path)) == 1


def test_json_is_not_an_object(tmp_path: Path) -> None:
    path = tmp_path / "case.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert len(problems_of(path)) == 1


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_json_constants_are_rejected(tmp_path: Path, constant: str) -> None:
    """json.loads принимает NaN и Infinity по умолчанию, хотя в JSON их нет."""
    path = write_input(tmp_path)
    path.write_text(path.read_text(encoding="utf-8").replace('"cpus": 2', f'"cpus": {constant}'),
                    encoding="utf-8")
    assert len(problems_of(path)) == 1
    assert constant in problems_of(path)[0]


def test_huge_float_is_not_infinity(tmp_path: Path) -> None:
    """1e400 разбирается без ошибок и молча становится inf — ловим отдельно."""
    path = write_input(tmp_path)
    path.write_text(path.read_text(encoding="utf-8").replace('"cpus": 2', '"cpus": 1e400'),
                    encoding="utf-8")
    only_problem(path, "limits.cpus")


# ---------------------------------------------------------------------------
# Все проблемы сразу
# ---------------------------------------------------------------------------

def test_all_problems_are_reported_at_once(tmp_path: Path) -> None:
    path = write_input(
        tmp_path,
        protocol_version="2.0",
        brief="",
        case_id="без-слеша",
        difficulty="ultra",
        seed="4107",
    )
    found = problems_of(path)
    assert len(found) == 5
    assert {problem.split(":")[0] for problem in found} == {
        "protocol_version", "brief", "case_id", "difficulty", "seed",
    }


def test_error_message_contains_every_problem(tmp_path: Path) -> None:
    path = write_input(tmp_path, brief="", team="")
    with pytest.raises(InputError) as info:
        load_input(path)
    assert "brief" in str(info.value)
    assert "team" in str(info.value)


def test_every_missing_field_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "inputs" / "case.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    assert len(problems_of(path)) == len(base_input())


# ---------------------------------------------------------------------------
# Отдельные поля
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field", sorted(base_input()))
def test_missing_field_is_a_problem(tmp_path: Path, field: str) -> None:
    only_problem(write_input(tmp_path, **{field: MISSING}), field)


def test_wrong_protocol_version(tmp_path: Path) -> None:
    assert "1.0" in only_problem(write_input(tmp_path, protocol_version="0.9"), "protocol_version")


@pytest.mark.parametrize("field", ["brief", "source", "team", "case_id"])
def test_empty_string_is_a_problem(tmp_path: Path, field: str) -> None:
    only_problem(write_input(tmp_path, **{field: "   "}), field)


@pytest.mark.parametrize("field", ["brief", "case_id", "protocol_version", "source", "team"])
def test_non_string_is_a_problem(tmp_path: Path, field: str) -> None:
    only_problem(write_input(tmp_path, **{field: 42}), field)


def test_missing_repository(tmp_path: Path) -> None:
    only_problem(write_input(tmp_path, repository="../нет-такой-папки"), "repository")


def test_repository_is_a_file(tmp_path: Path) -> None:
    only_problem(write_input(tmp_path, repository="../meridian/README.md"), "repository")


@pytest.mark.parametrize("output_dir", [
    "../meridian",
    "../meridian/runs",
    "../meridian/runs/team-example",
    "../meridian/../meridian/runs",
])
def test_output_dir_inside_repository_is_a_problem(tmp_path: Path, output_dir: str) -> None:
    """Результат внутри исходника сломал бы финальную сверку «репозиторий не изменён»."""
    found = problems_of(write_input(tmp_path, output_dir=output_dir))
    assert any("внутри repository" in problem for problem in found), found


def test_sibling_of_repository_is_allowed(tmp_path: Path) -> None:
    """Проверка по пути целиком, а не по префиксу строки: meridian-runs не внутри meridian."""
    case = load_input(write_input(tmp_path, output_dir="../meridian-runs"))
    assert case.output_dir == tmp_path / "meridian-runs"


@pytest.mark.skipif(os.name != "nt", reason="регистр в путях не важен только на Windows")
def test_case_insensitive_on_windows(tmp_path: Path) -> None:
    found = problems_of(write_input(tmp_path, output_dir="../MERIDIAN/runs"))
    assert any("внутри repository" in problem for problem in found), found


def test_existing_output_dir_is_a_problem(tmp_path: Path) -> None:
    """Протокол запрещает перезаписывать существующие данные."""
    (tmp_path / "runs" / "case").mkdir(parents=True)
    only_problem(write_input(tmp_path), "output_dir")


def test_output_dir_as_existing_file_is_a_problem(tmp_path: Path) -> None:
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "case").write_bytes(b"")
    only_problem(write_input(tmp_path), "output_dir")


@pytest.mark.parametrize("value", ["ultra", "MEDIUM", ""])
def test_bad_difficulty(tmp_path: Path, value: str) -> None:
    only_problem(write_input(tmp_path, difficulty=value), "difficulty")


@pytest.mark.parametrize("value", ["python", "RU", "de"])
def test_bad_language(tmp_path: Path, value: str) -> None:
    only_problem(write_input(tmp_path, language=value), "language")


def test_allowed_values_are_listed_in_the_message(tmp_path: Path) -> None:
    message = only_problem(write_input(tmp_path, difficulty="ultra"), "difficulty")
    assert "easy" in message and "medium" in message and "hard" in message


@pytest.mark.parametrize("author", [
    {"name": "", "email": "a@b.c"},
    {"name": "Имя", "email": "  "},
    {"name": "Имя"},
    {"email": "a@b.c"},
    "Имя <a@b.c>",
    None,
])
def test_bad_author(tmp_path: Path, author: object) -> None:
    assert all(problem.startswith("author") for problem in problems_of(write_input(tmp_path, author=author)))


def test_both_author_fields_are_reported(tmp_path: Path) -> None:
    found = problems_of(write_input(tmp_path, author={"name": "", "email": ""}))
    assert len(found) == 2


@pytest.mark.parametrize("field", sorted(limits()))
@pytest.mark.parametrize("value", [0, -1, "1800", None, True])
def test_bad_limit(tmp_path: Path, field: str, value: object) -> None:
    only_problem(write_input(tmp_path, limits=limits(**{field: value})), f"limits.{field}")


@pytest.mark.parametrize("field", sorted(limits()))
def test_missing_limit(tmp_path: Path, field: str) -> None:
    values = limits()
    del values[field]
    only_problem(write_input(tmp_path, limits=values), f"limits.{field}")


def test_limits_is_not_an_object(tmp_path: Path) -> None:
    assert all(problem.startswith("limits") for problem in problems_of(write_input(tmp_path, limits=[1, 2])))


def test_all_bad_limits_are_reported(tmp_path: Path) -> None:
    found = problems_of(write_input(tmp_path, limits=limits(cpus=0, memory_mb=-1, storage_mb="много")))
    assert len(found) == 3


def test_fractional_cpus_is_allowed(tmp_path: Path) -> None:
    """cpus по контракту float: 1.5 ядра — нормальный лимит."""
    assert load_input(write_input(tmp_path, limits=limits(cpus=1.5))).limits.cpus == 1.5


def test_fractional_timeout_is_a_problem(tmp_path: Path) -> None:
    only_problem(write_input(tmp_path, limits=limits(agent_timeout_sec=1800.5)), "limits.agent_timeout_sec")


@pytest.mark.parametrize("value", ["4107", 41.07, None, True, False])
def test_bad_seed(tmp_path: Path, value: object) -> None:
    """true проходит isinstance(x, int) — эту дыру нужно закрывать явно."""
    only_problem(write_input(tmp_path, seed=value), "seed")


@pytest.mark.parametrize("value", [0, -1])
def test_seed_may_be_zero_or_negative(tmp_path: Path, value: int) -> None:
    """Протокол требует целое, про знак ничего не сказано."""
    assert load_input(write_input(tmp_path, seed=value)).seed == value


# ---------------------------------------------------------------------------
# case_id
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [
    "hackathon/settlement-001",
    "команда/название",
    "team.example/case_1",
    "a/b",
    "team/с пробелом внутри",
])
def test_good_case_id(tmp_path: Path, value: str) -> None:
    assert load_input(write_input(tmp_path, case_id=value)).case_id == value


@pytest.mark.parametrize("value", [
    "без-слеша",
    "a/b/c",
    "/название",
    "команда/",
    "/",
    "команда/ название",
    "команда /название",
    "./название",
    "команда/..",
    "команда\\название",
    "команда/назв\tание",
    "команда/назв\nание",
])
def test_bad_case_id(tmp_path: Path, value: str) -> None:
    only_problem(write_input(tmp_path, case_id=value), "case_id")


# ---------------------------------------------------------------------------
# Настоящий вход организаторов
# ---------------------------------------------------------------------------

def test_real_settlement_input_as_is() -> None:
    """Файл организаторов без единой правки: относительный "../meridian" обязан указать
    на materials/hackathon-participants/meridian. Папка runs/ там появляться не должна —
    она в .gitignore и создаётся только настоящим прогоном пайплайна."""
    case = load_input(MATERIALS / "inputs" / "settlement.json")
    assert case.repository == MATERIALS / "meridian"
    assert case.repository.is_dir()
    assert case.output_dir == MATERIALS / "runs" / "team-example"
    assert case.input_path == MATERIALS / "inputs" / "settlement.json"


def test_real_settlement_input(tmp_path: Path) -> None:
    """Тот же JSON, что у организаторов: меняем только два пути, чтобы тест не зависел
    от наличия runs/ и от расположения materials/."""
    data = json.loads((MATERIALS / "inputs" / "settlement.json").read_text(encoding="utf-8"))
    data["repository"] = str(MATERIALS / "meridian")
    data["output_dir"] = str(tmp_path / "runs" / "team-example")
    path = tmp_path / "settlement.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    case = load_input(path)
    assert case.case_id == "hackathon/settlement-001"
    assert case.difficulty is Difficulty.MEDIUM
    assert case.language is Language.RU
    assert case.seed == 4107
    assert case.limits.memory_mb == 4096
    assert case.repository.is_dir()
    assert "PostgreSQL16" in case.brief
