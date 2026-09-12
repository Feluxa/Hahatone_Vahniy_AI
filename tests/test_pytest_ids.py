"""Канонический вид идентификатора теста — один на все источники."""
import pytest

from harness.pytest_ids import (
    canonical_test_id,
    expected_file_path,
    make_test_id,
    relative_test_path,
    split_test_id,
)

CANONICAL = "tests/test_close.py::test_x"


@pytest.mark.parametrize("raw", [
    CANONICAL,
    "test_close.py::test_x",
    "/tests/test_close.py::test_x",
    "./tests/test_close.py::test_x",
    r"tests\test_close.py::test_x",
    "  tests/test_close.py :: test_x  ",
])
def test_all_prefix_forms_give_one_canonical_id(raw: str) -> None:
    assert canonical_test_id(raw) == CANONICAL


def test_canonical_form_is_idempotent() -> None:
    assert canonical_test_id(canonical_test_id(CANONICAL)) == CANONICAL


def test_subdirectories_survive() -> None:
    """Подпапка — часть идентификатора, схлопывать до имени файла нельзя."""
    assert canonical_test_id("sql/test_close.py::test_x") == "tests/sql/test_close.py::test_x"
    assert canonical_test_id("tests/sql/test_close.py::test_x") == "tests/sql/test_close.py::test_x"


def test_parametrized_variant_is_kept_whole() -> None:
    assert canonical_test_id("test_close.py::test_x[2026-01-01]") == "tests/test_close.py::test_x[2026-01-01]"


def test_class_based_id_is_kept_whole() -> None:
    assert canonical_test_id("test_close.py::TestClose::test_x") == "tests/test_close.py::TestClose::test_x"


def test_id_without_separator_is_returned_as_is() -> None:
    """Путь без ::  — это ошибка манифеста, выдумывать имя теста здесь нельзя."""
    assert canonical_test_id("test_close.py") == "test_close.py"


def test_relative_test_path_strips_leading_tests_once() -> None:
    assert relative_test_path("tests/test_close.py") == "test_close.py"
    assert relative_test_path("/tests/sql/test_close.py") == "sql/test_close.py"
    assert relative_test_path("test_close.py") == "test_close.py"
    # Вложенная папка tests внутри tests/ остаётся: срезается ровно один ведущий префикс.
    assert relative_test_path("tests/tests/test_close.py") == "tests/test_close.py"


def test_split_and_make_round_trip() -> None:
    relative_path, test_name = split_test_id("tests/sql/test_close.py::test_x")
    assert (relative_path, test_name) == ("sql/test_close.py", "test_x")
    assert make_test_id(relative_path, test_name) == "tests/sql/test_close.py::test_x"


def test_expected_path_keeps_directory_structure() -> None:
    assert expected_file_path("DOCS/release_sentinel.txt") == "expected/DOCS/release_sentinel.txt.expected"


@pytest.mark.parametrize(("left", "right"), [
    ("DOCS/release_sentinel.txt", "sql/release_sentinel.txt"),
    ("a__b/c.txt", "a/b__c.txt"),
    ("a/b/c.txt", "a/b_c.txt"),
])
def test_expected_paths_do_not_collide(left: str, right: str) -> None:
    """Склейка имени через разделитель схлопнула бы эти пары; структура папок — нет."""
    assert expected_file_path(left) != expected_file_path(right)


def test_expected_path_is_never_a_python_module() -> None:
    """Иначе pytest попытался бы собрать эталон защищённого тестового файла как тест."""
    assert expected_file_path("tests/test_existing.py").endswith(".expected")
    assert not expected_file_path("tests/test_existing.py").endswith(".py")


def test_expected_path_normalizes_separators() -> None:
    assert expected_file_path("/DOCS/x.txt") == "expected/DOCS/x.txt.expected"
    assert expected_file_path(r"DOCS\x.txt") == "expected/DOCS/x.txt.expected"
