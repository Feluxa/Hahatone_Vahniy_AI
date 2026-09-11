"""Мини-репозиторий для тестов harness/repo.

Фикстурные репозитории собираются на диске побайтно, а не хранятся в tests/repo/data/:
в .gitattributes включён `text=auto`, поэтому git нормализовал бы переводы строк при checkout
и эталонные хэши разъезжались бы между Windows и Linux. Здесь байты заданы явно.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

# Скрытый файл, вложенные папки, пустой файл, не-ASCII путь и содержимое, CRLF и нулевой байт.
# Имена a-b.txt / a.txt / a/b.txt ловят сортировку «по папкам» вместо лексикографической
# по полному пути: '-' (45) < '.' (46) < '/' (47).
TINY_REPO: dict[str, bytes] = {
    ".gitignore": b"__pycache__/\n",
    "README.md": b"# tiny\r\n",
    "a-b.txt": b"dash",
    "a.txt": b"A",
    "a/b.txt": b"B",
    "empty.txt": b"",
    "src/app.py": b"def main() -> None:\n    pass\n",
    "src/nested/deep/util.py": b"VALUE = 1\n",
    "docs/отчёт.md": "Итог\n".encode("utf-8"),
    "bin/blob.dat": b"\x00\x01\x02\xff\r\n",
}

TINY_REPO_PATHS = [
    ".gitignore",
    "README.md",
    "a-b.txt",
    "a.txt",
    "a/b.txt",
    "bin/blob.dat",
    "docs/отчёт.md",
    "empty.txt",
    "src/app.py",
    "src/nested/deep/util.py",
]


def build_repo(root: Path, files: Mapping[str, bytes]) -> Path:
    """Раскладывает files по диску под root. Ключи — относительные POSIX-пути."""
    for relative_path, content in files.items():
        target = root / Path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return root


def make_symlink(link: Path, target: Path, *, target_is_directory: bool = False) -> None:
    """Создаёт символьную ссылку или пропускает тест, если ОС не разрешает их создавать."""
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except (OSError, NotImplementedError) as exc:  # Windows без прав на симлинки
        pytest.skip(f"символьные ссылки недоступны: {exc}")
