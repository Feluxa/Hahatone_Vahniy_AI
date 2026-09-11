"""Запись result.json. Владелец: №1 (перенесено с №4).

Поля: protocol_version, case_id, status (ready|failed), task_path, evidence_path (относительно output_dir
или null), limitations (пустой массив при успехе), input_snapshot_sha256.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

from harness.contracts import PROTOCOL_VERSION, CaseResult, Status
from harness.serde import to_dict

RESULT_NAME = "result.json"
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class OutputError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def write_result(output_dir: Path, result: CaseResult) -> Path:
    """Пишет output_dir/result.json и возвращает путь к нему.

    Для №4 (pipeline/cli): вызывается только для output_dir, который создал сам харнесс, —
    load_input уже проверил, что папки не существовало. Писать результат в чужую папку нельзя.
    При InputError результат не пишется вообще (см. load_input), так что сюда попадают только
    status=ready и status=failed после успешного разбора входа.

    output_dir создаётся при необходимости: до этого момента его могло ещё не быть.
    Запись атомарная — недописанный result.json хуже отсутствующего.
    """
    _validate(result)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / RESULT_NAME
    payload = json.dumps(to_dict(result), ensure_ascii=False, indent=2) + "\n"
    temporary = output_dir / f".{RESULT_NAME}.tmp"
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


def _validate(result: CaseResult) -> None:
    problems: list[str] = []
    if result.protocol_version != PROTOCOL_VERSION:
        problems.append(
            f'protocol_version: ожидается "{PROTOCOL_VERSION}", получено "{result.protocol_version}"'
        )
    if not result.case_id.strip():
        problems.append("case_id: не должен быть пустым")

    artifacts = {"task_path": result.task_path, "evidence_path": result.evidence_path}
    for name, value in artifacts.items():
        if value is None:
            continue
        problem = _relative_path_problem(value)
        if problem is not None:
            problems.append(f'{name}: {problem}; получено "{value}"')

    if result.status is Status.FAILED and not result.limitations:
        problems.append("limitations: при status=failed нужна хотя бы одна причина")
    if result.status is Status.READY:
        empty = [name for name, value in artifacts.items() if value is None]
        if empty:
            problems.append(f"{', '.join(empty)}: при status=ready должны быть заполнены")
    if any(not limitation.strip() for limitation in result.limitations):
        problems.append("limitations: пустые строки недопустимы")

    digest = result.input_snapshot_sha256
    if digest is not None and not SHA256_HEX.match(digest):
        problems.append(
            f'input_snapshot_sha256: ожидается 64 символа [0-9a-f] или null, получено "{digest}"'
        )

    if problems:
        raise OutputError(problems)


def _relative_path_problem(value: str) -> str | None:
    """Протокол требует пути относительно output_dir; вовне указывать нельзя."""
    if not value.strip():
        return "путь не должен быть пустым"
    if "\\" in value:
        return "нужен POSIX-путь со слешами «/»"
    if PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute():
        return "путь должен быть относительным от output_dir"
    if ".." in PurePosixPath(value).parts:
        return "путь не должен выходить за output_dir"
    return None
