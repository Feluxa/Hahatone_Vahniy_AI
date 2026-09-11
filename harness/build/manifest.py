"""Генерация task/task.toml. Владелец: №1 (перенесено с №4).

Образец: hackathon-participants/example-case/task.toml.
schema_version = "1.1"; [task] name=case_id, description, authors; [metadata] task_type="agentic",
bank_domain, language, build_tool="docker", difficulty, source, team, fail_to_pass, pass_to_pass, anti_cheat;
[agent] timeout_sec; [verifier] timeout_sec; [environment] allow_internet=false, build_timeout_sec, cpus,
memory_mb, storage_mb. Лимиты и автор — из входа.
"""
from __future__ import annotations

from pathlib import Path

from harness.contracts import CaseInput, CaseSpec, TestLists


def render_task_toml(case: CaseInput, spec: CaseSpec, lists: TestLists) -> str:
    raise NotImplementedError


def read_test_lists(task_toml: Path) -> TestLists:
    """Обратная операция: списки тестов из готового task.toml (нужна №3 для прогонов)."""
    raise NotImplementedError
