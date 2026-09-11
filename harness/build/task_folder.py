"""Сборка папки task/ на диске из CaseDraft. Владелец: №1.

task/
  task.toml, instruction.md
  environment/Dockerfile, environment/requirements.txt (если нужен), environment/repo/ (чистая копия)
  tests/test.sh, tests/conftest.py (шаблоны №3) + test_files из черновика
  solution/solve.sh (+ solution_files)
Шаблоны окружения и тестов берутся из harness.build.environment (№3).
"""
from __future__ import annotations

from pathlib import Path

from harness.contracts import CaseDraft, CaseInput, RunProfile


def write_task_folder(
    task_dir: Path, case: CaseInput, draft: CaseDraft, profile: RunProfile, workspace_repo: Path,
) -> None:
    raise NotImplementedError
