"""Индекс Python-символов через ast. Владелец: №1."""
from __future__ import annotations

from pathlib import Path

from harness.contracts import PythonSymbol


def index_python(repo: Path, paths: list[str]) -> list[PythonSymbol]:
    raise NotImplementedError
