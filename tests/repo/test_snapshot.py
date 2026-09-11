"""Хэш снимка исходного репозитория (PROTOCOL.md, раздел 2).

Фикстурный репозиторий строится в tmp_path побайтно — почему именно так, см. tests/repo/tiny_repo.py.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from harness.repo.snapshot import SnapshotError, compute_snapshot_sha256, list_regular_files
from tests.repo.tiny_repo import TINY_REPO, TINY_REPO_PATHS, build_repo, make_symlink

EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def reference_snapshot(root: Path) -> str:
    """Независимая наивная реализация алгоритма из PROTOCOL.md — для сверки с harness.repo.snapshot."""
    paths = sorted(
        item.relative_to(root).as_posix()
        for item in root.rglob("*")
        if not item.is_symlink() and item.is_file()
    )
    blob = "".join(f"{path}\0{hashlib.sha256((root / path).read_bytes()).hexdigest()}\n" for path in paths)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@pytest.fixture()
def tiny_repo(tmp_path: Path) -> Path:
    return build_repo(tmp_path / "repo", TINY_REPO)


# ---------------------------------------------------------------------------
# list_regular_files
# ---------------------------------------------------------------------------

def test_lists_hidden_and_nested_files(tiny_repo: Path) -> None:
    assert list_regular_files(tiny_repo) == TINY_REPO_PATHS


def test_paths_are_relative_posix(tiny_repo: Path) -> None:
    paths = list_regular_files(tiny_repo)
    assert all("\\" not in path for path in paths)
    assert all(not Path(path).is_absolute() for path in paths)


def test_order_is_lexicographic_by_full_path(tmp_path: Path) -> None:
    repo = build_repo(tmp_path / "repo", {"a.txt": b"", "a-b.txt": b"", "a/b.txt": b"", "b.txt": b""})
    assert list_regular_files(repo) == ["a-b.txt", "a.txt", "a/b.txt", "b.txt"]


def test_empty_directories_are_not_listed(tiny_repo: Path) -> None:
    (tiny_repo / "empty_dir" / "inner").mkdir(parents=True)
    assert list_regular_files(tiny_repo) == TINY_REPO_PATHS


def test_empty_repo_lists_nothing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert list_regular_files(repo) == []


def test_missing_root_raises(tmp_path: Path) -> None:
    with pytest.raises(SnapshotError):
        list_regular_files(tmp_path / "no-such-repo")


def test_file_as_root_raises(tiny_repo: Path) -> None:
    with pytest.raises(SnapshotError):
        list_regular_files(tiny_repo / "a.txt")


# ---------------------------------------------------------------------------
# compute_snapshot_sha256
# ---------------------------------------------------------------------------

def test_hash_matches_hand_built_preimage(tmp_path: Path) -> None:
    """Строка снимка ровно как в протоколе: путь, \\0, sha256 в lowercase hex, \\n."""
    repo = build_repo(tmp_path / "repo", {"a.txt": b"A", "dir/b.txt": b"B"})
    preimage = (
        "a.txt\0" + hashlib.sha256(b"A").hexdigest() + "\n"
        + "dir/b.txt\0" + hashlib.sha256(b"B").hexdigest() + "\n"
    )
    assert compute_snapshot_sha256(repo) == hashlib.sha256(preimage.encode("utf-8")).hexdigest()


def test_hash_matches_frozen_constant(tmp_path: Path) -> None:
    """Значение посчитано отдельным скриптом по тексту протокола: защита от одинаковой ошибки
    в реализации и в reference_snapshot."""
    repo = build_repo(tmp_path / "repo", {"a.txt": b"A", "dir/b.txt": b"B"})
    assert compute_snapshot_sha256(repo) == "8d5e67707a44de2aa3fbc2857fbccfedde90923be4d01a45261d9dc18ecfcf08"


def test_hash_matches_independent_implementation(tiny_repo: Path) -> None:
    assert compute_snapshot_sha256(tiny_repo) == reference_snapshot(tiny_repo)


def test_empty_repo_hash_is_sha256_of_empty_string(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert compute_snapshot_sha256(repo) == EMPTY_SHA256


def test_hash_is_lowercase_hex(tiny_repo: Path) -> None:
    digest = compute_snapshot_sha256(tiny_repo)
    assert len(digest) == 64
    assert digest == digest.lower()
    assert all(char in "0123456789abcdef" for char in digest)


def test_hash_does_not_depend_on_location_or_mtime(tmp_path: Path) -> None:
    first = build_repo(tmp_path / "one", TINY_REPO)
    second = build_repo(tmp_path / "two" / "deeper", TINY_REPO)
    (second / "a.txt").touch()
    assert compute_snapshot_sha256(first) == compute_snapshot_sha256(second)


def test_hash_is_stable_between_calls(tiny_repo: Path) -> None:
    assert compute_snapshot_sha256(tiny_repo) == compute_snapshot_sha256(tiny_repo)


def test_content_change_changes_hash(tiny_repo: Path) -> None:
    before = compute_snapshot_sha256(tiny_repo)
    (tiny_repo / "src" / "app.py").write_bytes(b"def main() -> None:\n    return\n")
    assert compute_snapshot_sha256(tiny_repo) != before


def test_hidden_file_change_changes_hash(tiny_repo: Path) -> None:
    """Скрытые файлы входят в снимок: в meridian это .gitignore."""
    before = compute_snapshot_sha256(tiny_repo)
    (tiny_repo / ".gitignore").write_bytes(b"__pycache__/\n.venv/\n")
    assert compute_snapshot_sha256(tiny_repo) != before


def test_line_endings_matter(tiny_repo: Path) -> None:
    """Файлы читаются в бинарном режиме: CRLF -> LF меняет хэш."""
    before = compute_snapshot_sha256(tiny_repo)
    (tiny_repo / "README.md").write_bytes(b"# tiny\n")
    assert compute_snapshot_sha256(tiny_repo) != before


def test_rename_changes_hash(tiny_repo: Path) -> None:
    """Путь входит в строку снимка, поэтому перемещение файла меняет хэш."""
    before = compute_snapshot_sha256(tiny_repo)
    (tiny_repo / "src" / "app.py").rename(tiny_repo / "src" / "main.py")
    assert compute_snapshot_sha256(tiny_repo) != before


def test_new_empty_file_changes_hash(tiny_repo: Path) -> None:
    before = compute_snapshot_sha256(tiny_repo)
    (tiny_repo / "extra.txt").write_bytes(b"")
    assert compute_snapshot_sha256(tiny_repo) != before


def test_empty_directory_does_not_change_hash(tiny_repo: Path) -> None:
    before = compute_snapshot_sha256(tiny_repo)
    (tiny_repo / "logs").mkdir()
    assert compute_snapshot_sha256(tiny_repo) == before


def test_large_file_is_read_in_chunks(tmp_path: Path) -> None:
    """Файл больше буфера чтения хэшируется целиком."""
    payload = bytes(range(256)) * 40_000  # ~10 МБ
    repo = build_repo(tmp_path / "repo", {"big.bin": payload})
    expected = "big.bin\0" + hashlib.sha256(payload).hexdigest() + "\n"
    assert compute_snapshot_sha256(repo) == hashlib.sha256(expected.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Символьные ссылки: в исходном наборе их нет, встретились — ошибка входа
# ---------------------------------------------------------------------------

def test_file_symlink_raises(tiny_repo: Path) -> None:
    make_symlink(tiny_repo / "link.txt", tiny_repo / "a.txt")
    with pytest.raises(SnapshotError) as info:
        compute_snapshot_sha256(tiny_repo)
    assert "link.txt" in str(info.value)


def test_directory_symlink_raises(tiny_repo: Path) -> None:
    make_symlink(tiny_repo / "src_link", tiny_repo / "src", target_is_directory=True)
    with pytest.raises(SnapshotError) as info:
        list_regular_files(tiny_repo)
    assert "src_link" in str(info.value)
