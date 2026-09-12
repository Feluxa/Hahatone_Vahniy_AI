"""Тесты для harness/llm/solution_writer.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.contracts import (
    CaseSpec,
    ContextFile,
    RepoContext,
    RunProfile,
    Trust,
)
from harness.llm.client import LlmClient, LlmResponse
from harness.llm.solution_writer import (
    _build_solve_sh_from_modifications,
    _validate_solve_sh,
    write_solution,
)


@pytest.fixture
def sample_spec() -> CaseSpec:
    return CaseSpec(
        goal="Устранить расхождение preview и SQL закрытия",
        behavior=["Возвраты уменьшают net_amount"],
        invariants=["Схема bank_settlement неизменна"],
        edge_cases=["Стык суток 00:00"],
        defect_hypothesis="В NettingPolicy.py net = purchases + refunds вместо вычитания",
        bank_domain="Расчеты",
        description="Согласование preview и SQL",
    )


@pytest.fixture
def sample_context() -> RepoContext:
    return RepoContext(
        snapshot_sha256="123sha",
        brief="Бриф",
        files=[
            ContextFile(
                path="backend/src/NettingPolicy.py",
                content="net = purchases + refunds",
                reason="policy",
                trust=Trust.TRUSTED,
            )
        ],
        python_symbols=[],
        sql_objects=[],
        existing_tests=[],
        run_profile=RunProfile(python_version="3.11", requirements_file=None),
    )


def test_build_solve_sh_from_modifications() -> None:
    mods = [
        {
            "file_path": "backend/src/NettingPolicy.py",
            "anchor": "net = purchases + refunds",
            "replacement": "net = purchases - refunds",
        }
    ]
    script = _build_solve_sh_from_modifications(mods)
    assert script.startswith("#!/bin/sh")
    assert "set -eu" in script
    assert "backend/src/NettingPolicy.py" in script
    assert "net = purchases - refunds" in script


def test_solve_sh_execution_replaces_correctly(tmp_path: Path) -> None:
    # Создаем фейковый репозиторий
    repo = tmp_path / "repo"
    repo.mkdir()
    policy_file = repo / "NettingPolicy.py"
    policy_file.write_text("purchases = 100\nrefunds = 30\nnet = purchases + refunds\n", encoding="utf-8")

    mods = [
        {
            "file_path": "NettingPolicy.py",
            "anchor": "net = purchases + refunds",
            "replacement": "net = purchases - refunds",
        }
    ]
    script = _build_solve_sh_from_modifications(mods)

    # Извлекаем внутренний python-скрипт и запускаем его
    py_code = script.split("python - <<'PY'")[1].rsplit("PY", 1)[0]
    res = subprocess.run(
        [sys.executable, "-c", py_code],
        env={"REPO_PATH": str(repo)},
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    updated_content = policy_file.read_text(encoding="utf-8")
    assert "net = purchases - refunds" in updated_content
    assert "net = purchases + refunds" not in updated_content


def test_solve_sh_execution_fails_if_anchor_count_not_one(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    policy_file = repo / "NettingPolicy.py"
    # Якорь повторяется дважды
    policy_file.write_text("line\nline\n", encoding="utf-8")

    mods = [
        {
            "file_path": "NettingPolicy.py",
            "anchor": "line",
            "replacement": "new_line",
        }
    ]
    script = _build_solve_sh_from_modifications(mods)
    py_code = script.split("python - <<'PY'")[1].rsplit("PY", 1)[0]
    res = subprocess.run(
        [sys.executable, "-c", py_code],
        env={"REPO_PATH": str(repo)},
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "Expected exactly 1 occurrence" in res.stderr


def test_validate_solve_sh_detects_forbidden_patterns() -> None:
    safe_script = "#!/bin/sh\nset -eu\necho 'patching'"
    assert len(_validate_solve_sh(safe_script)) == 0

    bad_script_1 = "#!/bin/sh\nrm -rf /tests"
    assert any("forbidden from referencing /tests" in p for p in _validate_solve_sh(bad_script_1))

    bad_script_2 = "#!/bin/sh\necho 1 > /logs/verifier/reward.txt"
    assert any("forbidden from writing reward.txt" in p for p in _validate_solve_sh(bad_script_2))

    bad_script_3 = "echo 'no shebang'"
    assert any("must start with a shebang" in p for p in _validate_solve_sh(bad_script_3))


def test_write_solution_success_from_modifications(sample_context: RepoContext, sample_spec: CaseSpec) -> None:
    mock_client = MagicMock(spec=LlmClient)
    solution_json = {
        "modifications": [
            {
                "file_path": "backend/src/NettingPolicy.py",
                "anchor": "net = purchases + refunds",
                "replacement": "net = purchases - refunds",
            }
        ],
        "explanation": "Исправлен знак возвратов",
    }
    mock_client.complete.return_value = LlmResponse(
        text=json.dumps(solution_json),
        model="GigaChat-3-Ultra",
        input_tokens=400,
        output_tokens=150,
        duration_sec=1.1,
    )

    files = write_solution(mock_client, sample_context, sample_spec)

    assert "solve.sh" in files
    assert "#!/bin/sh" in files["solve.sh"]
    assert "NettingPolicy.py" in files["solve.sh"]
    assert mock_client.complete.call_args.kwargs["purpose"] == "solution"


def test_write_solution_repair_on_forbidden_pattern(sample_context: RepoContext, sample_spec: CaseSpec) -> None:
    mock_client = MagicMock(spec=LlmClient)
    bad_json = {
        "solve_sh": "#!/bin/sh\necho 1 > /logs/verifier/reward.txt",
    }
    good_json = {
        "modifications": [
            {
                "file_path": "backend/src/NettingPolicy.py",
                "anchor": "net = purchases + refunds",
                "replacement": "net = purchases - refunds",
            }
        ],
    }

    mock_client.complete.side_effect = [
        LlmResponse(text=json.dumps(bad_json), model="GigaChat-3-Ultra", input_tokens=300, output_tokens=50, duration_sec=0.5),
        LlmResponse(text=json.dumps(good_json), model="GigaChat-3-Ultra", input_tokens=350, output_tokens=80, duration_sec=0.7),
    ]

    files = write_solution(mock_client, sample_context, sample_spec)

    assert "solve.sh" in files
    assert "reward.txt" not in files["solve.sh"]
    assert mock_client.complete.call_count == 2
    assert mock_client.complete.call_args_list[1].kwargs["purpose"] == "solution:repair"

