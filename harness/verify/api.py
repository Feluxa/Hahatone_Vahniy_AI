"""Единая точка входа в верификацию. Владелец: №3.

Этим будут пользоваться №2 (проверять черновики LLM) и №4 (pipeline). Сигнатуру не менять без чата.
На вход — готовая папка task/ на диске, поэтому эталонный golden/settlement-001 проверяется так же,
как сгенерированный кейс.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from harness.contracts import Limits, Mutant, RunResult, Verdict


@dataclass(frozen=True)
class VerifyOptions:
    repeat: bool = True
    run_mutants: bool = True
    extra_mutants: list[Mutant] = field(default_factory=list)   # LLM-мутанты от №2
    keep_image: bool = False


def verify_case(
    task_dir: Path, evidence_dir: Path, limits: Limits, options: VerifyOptions | None = None,
) -> tuple[list[RunResult], Verdict]:
    raise NotImplementedError
