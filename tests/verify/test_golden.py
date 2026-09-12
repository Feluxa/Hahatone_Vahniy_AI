import os
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path

import pytest

from harness.contracts import Limits, MutantSource
from harness.repo.workspace import copy_clean
from harness.verify.docker import DockerRunner
from harness.verify.mutation import hunk_revert_mutants, oracle_diff
from harness.verify.runs import run_apply_solution

GOLDEN_DIR = Path(__file__).resolve().parents[2] / "golden" / "settlement-001"
MERIDIAN = Path(__file__).resolve().parents[2] / "materials" / "hackathon-participants" / "meridian"


@pytest.fixture(scope="session", autouse=True)
def golden_base_repo() -> None:
    """Собирает golden/settlement-001/environment/repo, если его ещё нет.

    Исходный репозиторий внутри эталонного кейса не хранится в git (см. .gitignore), поэтому
    на чистой машине его надо получить из materials/ чистой копией — теми же правилами, по которым
    его соберёт харнесс. Если materials/ не выложены, фикстура ничего не делает: тесту, которому
    копия нужна, есть что сказать об этом самому.
    """
    base_repo = GOLDEN_DIR / "environment" / "repo"
    if base_repo.exists() or not MERIDIAN.is_dir():
        return
    copy_clean(MERIDIAN, base_repo)


def test_golden_task_toml_validity() -> None:
    task_toml = GOLDEN_DIR / "task.toml"
    assert task_toml.exists()
    data = tomllib.loads(task_toml.read_text(encoding="utf-8"))

    assert data["schema_version"] == "1.1"
    assert data["task"]["name"] == "hackathon/settlement-001"
    meta = data["metadata"]
    assert len(meta["fail_to_pass"]) == 4
    assert len(meta["pass_to_pass"]) == 5
    assert len(meta["anti_cheat"]) == 6

    # Проверка отсутствия дубликатов между списками
    all_tests = meta["fail_to_pass"] + meta["pass_to_pass"] + meta["anti_cheat"]
    assert len(all_tests) == len(set(all_tests))


def test_golden_instruction_no_leaks() -> None:
    instr = (GOLDEN_DIR / "instruction.md").read_text(encoding="utf-8")

    # Не должно быть имен тестовых функций
    assert "test_" not in instr
    # Не должно быть путей tests/ или solution/
    assert "tests/" not in instr
    assert "solution/" not in instr
    assert "solve.sh" not in instr

    # Обязаны быть названы все проверяемые инварианты
    assert "Europe/Moscow" in instr
    assert "LegacySettlementExporter" in instr
    assert "DOCS" in instr
    assert "bank_settlement" in instr


def test_golden_solution_diff_and_mutants() -> None:
    base_repo = GOLDEN_DIR / "environment" / "repo"
    solve_sh = GOLDEN_DIR / "solution" / "solve.sh"
    assert base_repo.exists()
    assert solve_sh.exists()

    with tempfile.TemporaryDirectory() as tmp:
        oracle_repo = Path(tmp) / "repo"
        shutil.copytree(base_repo, oracle_repo)

        sh_bin = shutil.which("sh")
        if sh_bin:
            res = subprocess.run(
                [sh_bin, str(solve_sh.resolve())],
                cwd=oracle_repo,
                env={**os.environ, "REPO_PATH": str(oracle_repo)},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        else:
            # На Windows без bash/sh извлекаем и выполняем вложенный Python-код
            import sys
            script_text = solve_sh.read_text(encoding="utf-8")
            py_code = script_text.split("<<'PY'\n")[1].rsplit("\nPY", 1)[0]
            res = subprocess.run(
                [sys.executable, "-c", py_code],
                cwd=oracle_repo,
                env={**os.environ, "REPO_PATH": str(oracle_repo)},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

        assert res.returncode == 0
        diff = oracle_diff(base_repo, oracle_repo)
        assert "NettingPolicy.py" in diff
        assert "061_refresh_daily_settlement.sql" in diff

        mutants = hunk_revert_mutants(diff)
        assert len(mutants) == 2
        mutant_names = {m.name for m in mutants}
        assert "hunk-1" in mutant_names
        assert "hunk-2" in mutant_names


@pytest.mark.docker
def test_golden_solution_applied_in_container_gives_same_mutants(tmp_path: Path) -> None:
    """Решение, применённое в контейнере, даёт тот же дифф и тех же hunk-мутантов.

    Эталон сверки — test_golden_solution_diff_and_mutants выше, который применяет тот же
    скрипт на хосте. Харнессу так делать нельзя (solve.sh пишет модель), поэтому боевой путь
    идёт через run_apply_solution, и здесь проверяется, что он даёт тот же результат.
    """
    base_repo = GOLDEN_DIR / "environment" / "repo"
    if not base_repo.is_dir():
        pytest.skip("materials/ не выложены, эталонная копия репозитория недоступна")

    limits = Limits(
        agent_timeout_sec=1800, verifier_timeout_sec=300, build_timeout_sec=1800,
        cpus=2, memory_mb=4096, storage_mb=10240,
    )
    runner = DockerRunner()
    image = "case-verifier:golden-apply-test"
    build_log = tmp_path / "build.log"

    build = runner.build(GOLDEN_DIR / "environment", image, timeout_sec=limits.build_timeout_sec,
                         log_path=build_log)
    assert build.ok, build_log.read_text(encoding="utf-8", errors="replace")[-2000:]

    try:
        oracle_repo = tmp_path / "oracle"
        run = run_apply_solution(
            task_dir=GOLDEN_DIR,
            evidence_dir=tmp_path / "evidence",
            image=image,
            limits=limits,
            oracle_repo=oracle_repo,
            image_digest=build.image_digest,
            runner=runner,
        )
        assert run.executed is True, run.note
        assert run.name == "oracle/apply"

        diff = oracle_diff(base_repo, oracle_repo)
        assert diff.strip()
        assert "NettingPolicy.py" in diff
        assert "061_refresh_daily_settlement.sql" in diff

        mutants = hunk_revert_mutants(diff)
        assert len(mutants) == 2
        assert {m.name for m in mutants} == {"hunk-1", "hunk-2"}
        assert {m.source for m in mutants} == {MutantSource.HUNK_REVERT}
    finally:
        runner.remove_image(image)
