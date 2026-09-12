"""Канонический вид идентификатора pytest-теста: ``tests/<путь внутри tests/>::<тест>``.

Один и тот же тест приходит из трёх мест, и префикс у каждого свой:

* от модели — ``test_settlement_close.py::test_x`` или ``tests/test_settlement_close.py::test_x``;
* из ``task.toml`` — как его записал предыдущий шаг;
* из прогона ``pytest --collect-only`` — относительно ``--rootdir=/``, то есть ``tests/...``.

Сравнивать их можно только после приведения к одному виду, иначе один и тот же тест выглядит
как два разных: списки расходятся с собранными тестами, а списки — с файлами черновика.

Канон — тот, что требует PROTOCOL.md (раздел 4): полный идентификатор вида
``tests/test_interval.py::test_right_boundary``. Путь внутри ``tests/`` сохраняется целиком,
подпапки не схлопываются: ``tests/sql/test_close.py::test_x`` остаётся собой.
"""
from __future__ import annotations

TESTS_DIR = "tests"
TESTS_PREFIX = f"{TESTS_DIR}/"
SEPARATOR = "::"

# Куда харнесс кладёт побайтные эталоны защищаемых файлов (CaseDraft.protected_files).
EXPECTED_DIR = "expected"
EXPECTED_SUFFIX = ".expected"


def expected_file_path(repo_relative_path: str) -> str:
    """Путь эталона внутри task/tests/ для файла репозитория.

    Структура папок исходника сохраняется целиком, поэтому DOCS/release_sentinel.txt и
    sql/release_sentinel.txt не схлопываются в один эталон. Склейка имени через разделитель
    тут не годится: 'a__b/c' и 'a/b__c' дали бы одно и то же имя.

    Суффикс .expected гарантирует, что ни один эталон не окажется .py-файлом и pytest не
    попытается собрать его как тест — даже если защищается тестовый файл самого репозитория.

        DOCS/release_sentinel.txt -> expected/DOCS/release_sentinel.txt.expected
    """
    cleaned = repo_relative_path.strip().replace("\\", "/").lstrip("/")
    return f"{EXPECTED_DIR}/{cleaned}{EXPECTED_SUFFIX}"


def relative_test_path(raw_path: str) -> str:
    """Путь файла тестов относительно ``task/tests/``: POSIX-слеши, без ведущего ``tests/``.

    Именно в таком виде путь лежит ключом в ``CaseDraft.test_files`` и именно его
    ``write_task_folder`` дописывает к ``task/tests/``.
    """
    cleaned = raw_path.strip().replace("\\", "/").lstrip("/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    if cleaned.startswith(TESTS_PREFIX):
        cleaned = cleaned[len(TESTS_PREFIX):]
    return cleaned


def make_test_id(relative_path: str, test_name: str) -> str:
    """Канонический идентификатор из пути внутри ``tests/`` и имени теста."""
    return f"{TESTS_PREFIX}{relative_test_path(relative_path)}{SEPARATOR}{test_name.strip()}"


def split_test_id(test_id: str) -> tuple[str, str]:
    """Идентификатор -> (путь относительно ``tests/``, имя теста).

    Для идентификатора без ``::`` имя теста пустое: проверять это — дело вызывающего
    (``manifest._check`` сообщает о таком отдельной проблемой).
    """
    cleaned = test_id.strip()
    if SEPARATOR not in cleaned:
        return relative_test_path(cleaned), ""
    path_part, test_name = cleaned.split(SEPARATOR, 1)
    return relative_test_path(path_part), test_name.strip()


def canonical_test_id(test_id: str) -> str:
    """Идентификатор в каноническом виде. Без ``::`` возвращается как есть, без выдумывания пути."""
    relative_path, test_name = split_test_id(test_id)
    if not test_name:
        return test_id.strip()
    return make_test_id(relative_path, test_name)
