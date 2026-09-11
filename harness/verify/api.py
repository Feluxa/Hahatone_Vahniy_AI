from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from harness.contracts import Limits, Mutant, Problem, RunKind, RunResult, RunScope, TestLists, Verdict
from harness.evidence.summary import write_summary
from harness.verify.docker import DockerRunner
from harness.verify.mutation import hunk_revert_mutants, oracle_diff
from harness.verify.runs import run_base_and_oracle, run_collect, run_mutants
from harness.verify.verdict import decide


@dataclass(frozen=True)
class VerifyOptions:
    repeat: bool = True
    run_mutants: bool = True
    extra_mutants: list[Mutant] = field(default_factory=list)   # LLM-мутанты от №2
    keep_image: bool = False


def _load_test_lists(task_dir: Path) -> TestLists:
    """Загружает TestLists из task.toml с поддержкой чтения через manifest или напрямую tomllib."""
    try:
        from harness.build.manifest import read_test_lists
        return read_test_lists(task_dir / "task.toml")
    except (ImportError, NotImplementedError):
        manifest_path = task_dir / "task.toml"
        if not manifest_path.exists():
            return TestLists(fail_to_pass=[], pass_to_pass=[], anti_cheat=[])
        data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        meta = data.get("metadata", {})
        return TestLists(
            fail_to_pass=meta.get("fail_to_pass", []),
            pass_to_pass=meta.get("pass_to_pass", []),
            anti_cheat=meta.get("anti_cheat", []),
        )


def _compute_hunk_mutants(task_dir: Path) -> list[Mutant]:
    """Вычисляет hunk-revert мутанты между исходным repo и repo после solve.sh."""
    base_repo = task_dir / "environment" / "repo"
    solve_script = task_dir / "solution" / "solve.sh"
    if not (base_repo.exists() and solve_script.exists()):
        return []

    with tempfile.TemporaryDirectory() as tmp:
        oracle_repo = Path(tmp) / "repo"
        shutil.copytree(base_repo, oracle_repo)
        try:
            res = subprocess.run(
                ["sh", str(solve_script.resolve())],
                cwd=oracle_repo,
                env={**os.environ, "REPO_PATH": str(oracle_repo)},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            if res.returncode == 0:
                diff = oracle_diff(base_repo, oracle_repo)
                return hunk_revert_mutants(diff)
        except Exception:
            pass
    return []


def verify_case(
    task_dir: Path, evidence_dir: Path, limits: Limits, options: VerifyOptions | None = None,
) -> tuple[list[RunResult], Verdict]:
    """Единая точка входа в верификацию кейса."""
    options = options or VerifyOptions()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    runner = DockerRunner()

    safe_name = task_dir.name.lower().replace("/", "-").replace("\\", "-")
    image_tag = f"case-verifier:{safe_name}"

    # 1. Сборка Docker-образа
    build_log_path = evidence_dir / "build.log"
    build_outcome = runner.build(
        task_dir / "environment",
        image_tag,
        timeout_sec=limits.build_timeout_sec,
        log_path=build_log_path,
    )

    build_run = RunResult(
        name="build",
        kind=RunKind.BUILD,
        scope=RunScope.FULL,
        executed=True,
        commands=[f"docker build -t {image_tag} ."],
        image_digest=build_outcome.image_digest,
        duration_sec=build_outcome.duration_sec,
        exit_code=0 if build_outcome.ok else 1,
        reward=None,
        report_path=None,
        log_dir=None,
        note="Timeout expired" if not build_outcome.ok and build_outcome.duration_sec >= limits.build_timeout_sec else None,
    )

    lists = _load_test_lists(task_dir)

    if not build_outcome.ok:
        runs = [build_run]
        verdict = decide(runs, lists, [])
        write_summary(evidence_dir, runs, verdict)
        return runs, verdict

    # 2. collect прогон
    collect_run = run_collect(
        task_dir=task_dir,
        evidence_dir=evidence_dir,
        image=image_tag,
        limits=limits,
        image_digest=build_outcome.image_digest,
        runner=runner,
    )

    # 3. base и oracle прогоны
    base_oracle_runs = run_base_and_oracle(
        task_dir=task_dir,
        evidence_dir=evidence_dir,
        image=image_tag,
        lists=lists,
        limits=limits,
        repeat=options.repeat,
        image_digest=build_outcome.image_digest,
        runner=runner,
    )

    # 4. Мутанты
    mutant_runs: list[RunResult] = []
    if options.run_mutants:
        hunk_mutants = _compute_hunk_mutants(task_dir)
        all_mutants = hunk_mutants + options.extra_mutants
        if all_mutants:
            mutant_runs = run_mutants(
                task_dir=task_dir,
                evidence_dir=evidence_dir,
                image=image_tag,
                lists=lists,
                limits=limits,
                mutants=all_mutants,
                image_digest=build_outcome.image_digest,
                runner=runner,
            )

    # 5. Статические проверки (если модуль реализован)
    static_problems: list[Problem] = []
    try:
        from harness.verify.static_checks import check_task_folder
        static_problems = check_task_folder(task_dir)
    except (ImportError, NotImplementedError, AttributeError):
        pass

    all_runs = [build_run, collect_run, *base_oracle_runs, *mutant_runs]
    verdict = decide(all_runs, lists, static_problems)

    # 6. Запись summary.json
    write_summary(evidence_dir, all_runs, verdict)

    # 7. Очистка образа
    if not options.keep_image:
        runner.remove_image(image_tag)

    return all_runs, verdict

