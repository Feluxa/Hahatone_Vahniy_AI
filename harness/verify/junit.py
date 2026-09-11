"""Разбор junit XML от pytest. Владелец: №3.

Нужно отличать failure (assert/исключение в теле теста) от error (фикстура, импорт, окружение):
на BASE fail_to_pass обязаны падать по assert (PROTOCOL.md, раздел 5, п.4).
ID в формате task.toml: "tests/test_x.py::test_name[param]".
"""
from __future__ import annotations

from pathlib import Path

from harness.contracts import TestReport


def parse_junit(xml_path: Path) -> dict[str, TestReport]:
    raise NotImplementedError


def with_missing(reports: dict[str, TestReport], expected_ids: list[str]) -> dict[str, TestReport]:
    """Добавляет TestOutcome.MISSING для ожидаемых, но не найденных ID."""
    raise NotImplementedError
