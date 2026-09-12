from __future__ import annotations

import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from harness.contracts import Limits, Mutant, Problem, RunKind, RunResult, RunScope, TestLists, Verdict
from harness.build.manifest import rewrite_test_lists
from harness.evidence.summary import write_summary
from harness.verify.docker import DockerRunner
from harness.verify.mutation import hunk_revert_mutants, oracle_diff
from harness.verify.runs import (
    run_apply_solution,
    run_collect,
    run_full_pair,
    run_list_scopes,
    run_mutants,
    run_repeats,
)
from harness.verify.static_checks import check_task_folder
from harness.verify.verdict import decide, reclassify_by_outcomes


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


def _compute_hunk_mutants(
    task_dir: Path, evidence_dir: Path, image: str, limits: Limits,
    *, image_digest: str | None, runner: DockerRunner,
) -> tuple[list[Mutant], RunResult]:
    """Hunk-revert мутанты из диффа эталонного решения.

    Решение применяется в контейнере (run_apply_solution), результат выкладывается во временную
    папку на хосте, и дифф считается обычным oracle_diff. Если прогон не удался, мутантов нет,
    и вместе с пустым списком возвращается его RunResult с причиной — вердикт обязан её увидеть.

    ignore_cleanup_errors: файлы из контейнера принадлежат root, и на Linux уборка временной
    папки может не пройти. Это не повод ронять верификацию.
    """
    base_repo = task_dir / "environment" / "repo"
    with tempfile.TemporaryDirectory(prefix="harness-oracle-", ignore_cleanup_errors=True) as tmp:
        oracle_repo = Path(tmp) / "repo"
        apply_run = run_apply_solution(
            task_dir=task_dir,
            evidence_dir=evidence_dir,
            image=image,
            limits=limits,
            oracle_repo=oracle_repo,
            image_digest=image_digest,
            runner=runner,
        )
        if not apply_run.executed:
            return [], apply_run
        return hunk_revert_mutants(oracle_diff(base_repo, oracle_repo)), apply_run


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

    # 3. Полные прогоны base и oracle
    phase_kwargs = {
        "task_dir": task_dir,
        "evidence_dir": evidence_dir,
        "image": image_tag,
        "limits": limits,
        "image_digest": build_outcome.image_digest,
        "runner": runner,
    }
    full_runs = run_full_pair(lists=lists, **phase_kwargs)

    # 3a. Раскладка по фактическим исходам — до прогонов по спискам, иначе они пойдут
    # по неверной раскладке и дадут ложные REWARD_WRONG. Манифест догоняет изменение.
    lists, notes = reclassify_by_outcomes(lists, full_runs)
    if notes:
        rewrite_test_lists(task_dir / "task.toml", lists)

    # 3b. Прогоны по спискам и независимые повторы
    base_oracle_runs = [
        *full_runs,
        *run_list_scopes(lists=lists, **phase_kwargs),
    ]
    if options.repeat:
        base_oracle_runs += run_repeats(lists=lists, **phase_kwargs)

    # 4. Мутанты
    mutant_runs: list[RunResult] = []
    apply_runs: list[RunResult] = []
    if options.run_mutants:
        hunk_mutants, apply_run = _compute_hunk_mutants(
            task_dir, evidence_dir, image_tag, limits,
            image_digest=build_outcome.image_digest, runner=runner,
        )
        apply_runs = [apply_run]
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

    # 5. Статические проверки (владелец: №4).
    # Без try: модуль собран и обязателен. Проглоченное исключение отключало разом все
    # проверки — утечки в instruction.md, skip/xfail, мусор в task/, обращение solve.sh
    # к /tests — и кейс получал ready.
    static_problems: list[Problem] = check_task_folder(task_dir, lists)

    all_runs = [build_run, collect_run, *base_oracle_runs, *apply_runs, *mutant_runs]
    verdict = decide(all_runs, lists, static_problems, notes=notes)

    # 6. Запись summary.json
    write_summary(evidence_dir, all_runs, verdict)

    # 7. Очистка образа
    if not options.keep_image:
        runner.remove_image(image_tag)

    return all_runs, verdict

