"""Запись result.json. Владелец: №1 (перенесено с №4).

Поля: protocol_version, case_id, status (ready|failed), task_path, evidence_path (относительно output_dir
или null), limitations (пустой массив при успехе), input_snapshot_sha256.
"""
from __future__ import annotations

from pathlib import Path

from harness.contracts import CaseResult


def write_result(output_dir: Path, result: CaseResult) -> Path:
    raise NotImplementedError
