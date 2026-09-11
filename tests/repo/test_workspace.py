"""Чистая копия репозитория (PROTOCOL.md, раздел 3: в папке кейса нет кэшей, venv и истории git).

Копия делается дважды: в workspace, где работает харнесс, и в task/environment/repo/.
Исходник при этом только читается — это проверяется хэшем снимка до и после.
"""

from __future__ import annotations

import errno
import os
import shutil
from pathlib import Path

import pytest

from harness.repo.snapshot import compute_snapshot_sha256, list_regular_files
from harness.repo.workspace import IGNORED_NAMES, IGNORED_SUFFIXES, WorkspaceError, copy_clean
from tests.repo.tiny_repo import TINY_REPO, TINY_REPO_PATHS, build_repo, make_symlink

# Мусор, который обязан остаться за бортом: на верхнем уровне и во вложенных папках.
JUNK: dict[str, bytes] = {
    ".git/config": b"[core]\n",
    ".git/objects/ab/cdef": b"\x00binary",
    ".venv/pyvenv.cfg": b"home = /usr\n",
    ".venv/Lib/site.py": b"pass\n",
    "venv/pyvenv.cfg": b"home = /usr\n",
    ".pytest_cache/CACHEDIR.TAG": b"Signature\n",
    ".mypy_cache/cache.json": b"{}",
    ".ruff_cache/content": b"cached\n",
    ".idea/workspace.xml": b"<project/>",
    ".vscode/settings.json": b"{}",
    "node_modules/pkg/index.js": b"module.exports = 1;\n",
    ".DS_Store": b"\x00\x00",
    "docs/.DS_Store": b"\x00\x00",
    "src/__pycache__/app.cpython-311.pyc": b"\x00compiled",
    "src/legacy.pyo": b"\x00optimized",
    "build/artifact.pyc": b"\x00compiled",
}

# Имена, похожие на мусорные, но это обычные файлы проекта: совпадение должно быть точным,
# а не «начинается с» или «содержит».
LOOKALIKES: dict[str, bytes] = {
    "venv_tools/run.py": b"pass\n",          # не venv
    "notes.pyc.md": b"# about .pyc\n",       # не оканчивается на .pyc
    "git/history.md": b"# not .git\n",       # не .git
}

EXPECTED_SKIPPED = [
    ".DS_Store",
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    "build/artifact.pyc",
    "docs/.DS_Store",
    "node_modules",
    "src/__pycache__",
    "src/legacy.pyo",
    "venv",
]


@pytest.fixture()
def clean_src(tmp_path: Path) -> Path:
    return build_repo(tmp_path / "src", TINY_REPO)


@pytest.fixture()
def dirty_src(tmp_path: Path) -> Path:
    return build_repo(tmp_path / "src", {**TINY_REPO, **JUNK, **LOOKALIKES})


# ---------------------------------------------------------------------------
# Копия целиком и побайтно
# ---------------------------------------------------------------------------

def test_copies_every_file_including_hidden(clean_src: Path, tmp_path: Path) -> None:
    copy_clean(clean_src, tmp_path / "dst")
    assert list_regular_files(tmp_path / "dst") == TINY_REPO_PATHS


def test_content_is_byte_identical(clean_src: Path, tmp_path: Path) -> None:
    """CRLF, нулевые байты и пустые файлы переносятся как есть."""
    dst = tmp_path / "dst"
    copy_clean(clean_src, dst)
    for relative_path, content in TINY_REPO.items():
        assert (dst / relative_path).read_bytes() == content


def test_copy_has_the_same_snapshot_hash(clean_src: Path, tmp_path: Path) -> None:
    dst = tmp_path / "dst"
    copy_clean(clean_src, dst)
    assert compute_snapshot_sha256(dst) == compute_snapshot_sha256(clean_src)


def test_nothing_is_skipped_in_a_clean_repo(clean_src: Path, tmp_path: Path) -> None:
    assert copy_clean(clean_src, tmp_path / "dst") == []


def test_empty_directories_are_preserved(clean_src: Path, tmp_path: Path) -> None:
    (clean_src / "logs").mkdir()
    copy_clean(clean_src, tmp_path / "dst")
    assert (tmp_path / "dst" / "logs").is_dir()


def test_destination_parents_are_created(clean_src: Path, tmp_path: Path) -> None:
    dst = tmp_path / "work" / "case" / "repo"
    copy_clean(clean_src, dst)
    assert (dst / "a.txt").read_bytes() == b"A"


# ---------------------------------------------------------------------------
# Мусор не копируется
# ---------------------------------------------------------------------------

def test_junk_is_not_copied(dirty_src: Path, tmp_path: Path) -> None:
    dst = tmp_path / "dst"
    copy_clean(dirty_src, dst)
    copied = list_regular_files(dst)
    assert copied == sorted([*TINY_REPO_PATHS, *LOOKALIKES])
    assert not any(name in IGNORED_NAMES for path in copied for name in path.split("/"))
    assert not any(path.endswith(IGNORED_SUFFIXES) for path in copied)


def test_skipped_paths_are_reported(dirty_src: Path, tmp_path: Path) -> None:
    assert copy_clean(dirty_src, tmp_path / "dst") == sorted(EXPECTED_SKIPPED)


def test_skipped_directory_is_reported_once(dirty_src: Path, tmp_path: Path) -> None:
    """Для .git возвращается сама папка, а не тысячи путей внутри неё."""
    skipped = copy_clean(dirty_src, tmp_path / "dst")
    assert ".git" in skipped
    assert not any(path.startswith(".git/") for path in skipped)


def test_lookalike_names_are_kept(dirty_src: Path, tmp_path: Path) -> None:
    """.gitignore не .git, venv_tools не venv, notes.pyc.md не .pyc."""
    dst = tmp_path / "dst"
    copy_clean(dirty_src, dst)
    assert (dst / ".gitignore").exists()
    assert (dst / "venv_tools" / "run.py").exists()
    assert (dst / "notes.pyc.md").exists()
    assert (dst / "git" / "history.md").exists()


def test_ignored_directory_leaves_no_trace(dirty_src: Path, tmp_path: Path) -> None:
    dst = tmp_path / "dst"
    copy_clean(dirty_src, dst)
    assert not (dst / ".git").exists()
    assert not (dst / "src" / "__pycache__").exists()


def test_directory_with_only_junk_stays_empty(dirty_src: Path, tmp_path: Path) -> None:
    """build/ содержал только artifact.pyc: папка есть, файла нет — на хэш это не влияет."""
    dst = tmp_path / "dst"
    copy_clean(dirty_src, dst)
    assert (dst / "build").is_dir()
    assert list((dst / "build").iterdir()) == []


@pytest.mark.parametrize("name", sorted(IGNORED_NAMES))
def test_each_ignored_name_is_skipped_at_any_depth(clean_src: Path, tmp_path: Path, name: str) -> None:
    build_repo(clean_src, {f"{name}/inside.txt": b"junk", f"src/nested/{name}/inside.txt": b"junk"})
    skipped = copy_clean(clean_src, tmp_path / "dst")
    assert skipped == sorted([name, f"src/nested/{name}"])


@pytest.mark.parametrize("suffix", IGNORED_SUFFIXES)
def test_each_ignored_suffix_is_skipped_at_any_depth(clean_src: Path, tmp_path: Path, suffix: str) -> None:
    build_repo(clean_src, {f"top{suffix}": b"junk", f"src/nested/deep/mod{suffix}": b"junk"})
    skipped = copy_clean(clean_src, tmp_path / "dst")
    assert skipped == sorted([f"src/nested/deep/mod{suffix}", f"top{suffix}"])


# ---------------------------------------------------------------------------
# Исходник не меняется
# ---------------------------------------------------------------------------

def test_source_is_left_untouched(dirty_src: Path, tmp_path: Path) -> None:
    before = compute_snapshot_sha256(dirty_src)
    copy_clean(dirty_src, tmp_path / "dst")
    assert compute_snapshot_sha256(dirty_src) == before


def test_copy_is_independent_of_source(clean_src: Path, tmp_path: Path) -> None:
    """Правка копии не задевает исходник: это настоящие файлы, а не ссылки."""
    dst = tmp_path / "dst"
    copy_clean(clean_src, dst)
    (dst / "a.txt").write_bytes(b"changed")
    assert (clean_src / "a.txt").read_bytes() == b"A"


# ---------------------------------------------------------------------------
# Ошибки
# ---------------------------------------------------------------------------

def test_existing_destination_raises(clean_src: Path, tmp_path: Path) -> None:
    dst = tmp_path / "dst"
    dst.mkdir()
    with pytest.raises(WorkspaceError):
        copy_clean(clean_src, dst)


def test_missing_source_raises(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError):
        copy_clean(tmp_path / "no-such-repo", tmp_path / "dst")


def test_file_as_source_raises(clean_src: Path, tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError):
        copy_clean(clean_src / "a.txt", tmp_path / "dst")


def test_symlink_in_source_raises(clean_src: Path, tmp_path: Path) -> None:
    dst = tmp_path / "dst"
    make_symlink(clean_src / "link.txt", clean_src / "a.txt")
    with pytest.raises(WorkspaceError) as info:
        copy_clean(clean_src, dst)
    assert "link.txt" in str(info.value)
    assert not dst.exists()


def test_failed_copy_removes_destination(clean_src: Path, tmp_path: Path, monkeypatch) -> None:
    """Сорвавшееся копирование не оставляет полуготовую папку: иначе следующий запуск упадёт
    на «назначение существует» и настоящая причина будет не видна. Исходная ошибка проходит как есть."""
    dst = tmp_path / "work" / "dst"
    real_copy2 = shutil.copy2

    def copy2_out_of_space(source, target, *args, **kwargs):  # type: ignore[no-untyped-def]
        if Path(target).name == "app.py":
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_copy2(source, target, *args, **kwargs)

    monkeypatch.setattr(shutil, "copy2", copy2_out_of_space)
    with pytest.raises(OSError) as info:
        copy_clean(clean_src, dst)
    assert info.value.errno == errno.ENOSPC
    assert not isinstance(info.value, WorkspaceError)
    assert not dst.exists()


@pytest.mark.skipif(os.name != "posix", reason="бит исполняемости есть только в POSIX")
def test_executable_bit_is_preserved(clean_src: Path, tmp_path: Path) -> None:
    """В репозитории могут быть скрипты; в контейнере они должны остаться исполняемыми."""
    script = clean_src / "run.sh"
    script.write_bytes(b"#!/bin/sh\necho hi\n")
    script.chmod(0o755)
    dst = tmp_path / "dst"
    copy_clean(clean_src, dst)
    assert (dst / "run.sh").stat().st_mode & 0o111
