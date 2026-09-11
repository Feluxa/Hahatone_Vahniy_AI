from __future__ import annotations

from pathlib import Path

from harness.contracts import Limits, Mutant, RunKind, RunResult, RunScope, TestLists, TestOutcome, TestReport
from harness.verify.docker import DockerRunner, Mount
from harness.verify.junit import parse_junit, with_missing


def _target_arg(test_id: str) -> str:
    """Преобразует 'tests/test_x.py::test_y' в '/tests/test_x.py::test_y'."""
    clean = test_id.lstrip("/")
    if clean.startswith("tests/"):
        return f"/{clean}"
    return f"/tests/{clean}"


def _execute_run(
    *,
    runner: DockerRunner,
    image: str,
    image_digest: str | None,
    name: str,
    kind: RunKind,
    scope: RunScope,
    command: list[str],
    task_dir: Path,
    evidence_dir: Path,
    limits: Limits,
    expected_ids: list[str],
    with_solution: bool = False,
    repeat_of: str | None = None,
    mutant_patch: str | None = None,
) -> RunResult:
    run_log_dir = evidence_dir / name
    run_log_dir.mkdir(parents=True, exist_ok=True)

    mounts = [
        Mount(host=task_dir / "tests", container="/tests", read_only=True),
        Mount(host=run_log_dir, container="/logs", read_only=False),
    ]
    if with_solution or mutant_patch is not None:
        mounts.append(Mount(host=task_dir / "solution", container="/solution", read_only=True))

    actual_cmd = command
    if mutant_patch is not None:
        # Пишем патч во временный файл внутри log_dir (который смонтирован как /logs)
        patch_file = run_log_dir / "mutant.patch"
        patch_file.write_text(mutant_patch, encoding="utf-8")
        actual_cmd = [
            "sh", "-c",
            "sh /solution/solve.sh && patch -p1 -d /app/repo < /logs/mutant.patch && sh /tests/test.sh",
        ]
    elif with_solution:
        actual_cmd = [
            "sh", "-c",
            "sh /solution/solve.sh && " + " ".join(command),
        ]

    outcome = runner.run(
        image=image,
        command=actual_cmd,
        mounts=mounts,
        limits=limits,
        timeout_sec=limits.verifier_timeout_sec,
        log_dir=run_log_dir,
    )

    reward_file = run_log_dir / "verifier" / "reward.txt"
    reward: int | None = None
    if reward_file.exists():
        try:
            reward = int(reward_file.read_text(encoding="utf-8").strip())
        except ValueError:
            reward = None

    tests_xml = run_log_dir / "verifier" / "tests.xml"
    reports: dict[str, TestReport] = {}
    report_rel: str | None = None
    if tests_xml.exists():
        reports = parse_junit(tests_xml)
        if expected_ids:
            reports = with_missing(reports, expected_ids)
        report_rel = f"{name}/verifier/tests.xml"

    executed = not outcome.timed_out and outcome.exit_code is not None

    return RunResult(
        name=name,
        kind=kind,
        scope=scope,
        executed=executed,
        commands=[" ".join(actual_cmd)] if len(actual_cmd) > 1 else actual_cmd,
        image_digest=image_digest,
        duration_sec=outcome.duration_sec,
        exit_code=outcome.exit_code,
        reward=reward,
        report_path=report_rel,
        log_dir=name,
        tests=reports,
        repeat_of=repeat_of,
        note="Timeout expired" if outcome.timed_out else None,
    )


def run_collect(
    task_dir: Path, evidence_dir: Path, image: str, limits: Limits,
    *, image_digest: str | None = None, runner: DockerRunner | None = None,
) -> RunResult:
    """Запуск pytest --collect-only в контейнере."""
    runner = runner or DockerRunner()
    run_log_dir = evidence_dir / "collect"
    run_log_dir.mkdir(parents=True, exist_ok=True)

    mounts = [
        Mount(host=task_dir / "tests", container="/tests", read_only=True),
        Mount(host=run_log_dir, container="/logs", read_only=False),
    ]
    cmd = ["python", "-m", "pytest", "--rootdir=/", "/tests", "--collect-only", "-q"]
    outcome = runner.run(
        image=image,
        command=cmd,
        mounts=mounts,
        limits=limits,
        timeout_sec=limits.verifier_timeout_sec,
        log_dir=run_log_dir,
    )

    collected_tests: dict[str, TestReport] = {}
    stdout_file = outcome.stdout_path
    if stdout_file.exists():
        for line in stdout_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if "::" in line and not line.startswith("="):
                test_id = line.lstrip("/")
                if not test_id.startswith("tests/"):
                    test_id = f"tests/{test_id}"
                collected_tests[test_id] = TestReport(outcome=TestOutcome.PASSED)

    return RunResult(
        name="collect",
        kind=RunKind.BASE,
        scope=RunScope.COLLECT,
        executed=not outcome.timed_out and outcome.exit_code == 0,
        commands=[" ".join(cmd)],
        image_digest=image_digest,
        duration_sec=outcome.duration_sec,
        exit_code=outcome.exit_code,
        reward=None,
        report_path=None,
        log_dir="collect",
        tests=collected_tests,
        note="Timeout expired" if outcome.timed_out else None,
    )


def run_base_and_oracle(
    task_dir: Path, evidence_dir: Path, image: str, lists: TestLists, limits: Limits,
    *, repeat: bool = True, image_digest: str | None = None, runner: DockerRunner | None = None,
) -> list[RunResult]:
    """Выполняет матрицу прогонов base и oracle: full, по спискам, и повторы."""
    runner = runner or DockerRunner()
    runs: list[RunResult] = []

    all_ids = lists.all_ids()

    # 1. base/full
    runs.append(_execute_run(
        runner=runner, image=image, image_digest=image_digest,
        name="base/full", kind=RunKind.BASE, scope=RunScope.FULL,
        command=["sh", "/tests/test.sh"],
        task_dir=task_dir, evidence_dir=evidence_dir, limits=limits,
        expected_ids=all_ids, with_solution=False,
    ))

    # 2. base/fail_to_pass
    if lists.fail_to_pass:
        runs.append(_execute_run(
            runner=runner, image=image, image_digest=image_digest,
            name="base/fail_to_pass", kind=RunKind.BASE, scope=RunScope.FAIL_TO_PASS,
            command=["sh", "/tests/test.sh", *[_target_arg(x) for x in lists.fail_to_pass]],
            task_dir=task_dir, evidence_dir=evidence_dir, limits=limits,
            expected_ids=lists.fail_to_pass, with_solution=False,
        ))

    # 3. base/pass_to_pass
    if lists.pass_to_pass:
        runs.append(_execute_run(
            runner=runner, image=image, image_digest=image_digest,
            name="base/pass_to_pass", kind=RunKind.BASE, scope=RunScope.PASS_TO_PASS,
            command=["sh", "/tests/test.sh", *[_target_arg(x) for x in lists.pass_to_pass]],
            task_dir=task_dir, evidence_dir=evidence_dir, limits=limits,
            expected_ids=lists.pass_to_pass, with_solution=False,
        ))

    # 4. base/anti_cheat
    if lists.anti_cheat:
        runs.append(_execute_run(
            runner=runner, image=image, image_digest=image_digest,
            name="base/anti_cheat", kind=RunKind.BASE, scope=RunScope.ANTI_CHEAT,
            command=["sh", "/tests/test.sh", *[_target_arg(x) for x in lists.anti_cheat]],
            task_dir=task_dir, evidence_dir=evidence_dir, limits=limits,
            expected_ids=lists.anti_cheat, with_solution=False,
        ))

    # 5. oracle/full
    runs.append(_execute_run(
        runner=runner, image=image, image_digest=image_digest,
        name="oracle/full", kind=RunKind.ORACLE, scope=RunScope.FULL,
        command=["sh", "/tests/test.sh"],
        task_dir=task_dir, evidence_dir=evidence_dir, limits=limits,
        expected_ids=all_ids, with_solution=True,
    ))

    # 6. oracle/fail_to_pass
    if lists.fail_to_pass:
        runs.append(_execute_run(
            runner=runner, image=image, image_digest=image_digest,
            name="oracle/fail_to_pass", kind=RunKind.ORACLE, scope=RunScope.FAIL_TO_PASS,
            command=["sh", "/tests/test.sh", *[_target_arg(x) for x in lists.fail_to_pass]],
            task_dir=task_dir, evidence_dir=evidence_dir, limits=limits,
            expected_ids=lists.fail_to_pass, with_solution=True,
        ))

    # 7. oracle/pass_to_pass
    if lists.pass_to_pass:
        runs.append(_execute_run(
            runner=runner, image=image, image_digest=image_digest,
            name="oracle/pass_to_pass", kind=RunKind.ORACLE, scope=RunScope.PASS_TO_PASS,
            command=["sh", "/tests/test.sh", *[_target_arg(x) for x in lists.pass_to_pass]],
            task_dir=task_dir, evidence_dir=evidence_dir, limits=limits,
            expected_ids=lists.pass_to_pass, with_solution=True,
        ))

    # 8. oracle/anti_cheat
    if lists.anti_cheat:
        runs.append(_execute_run(
            runner=runner, image=image, image_digest=image_digest,
            name="oracle/anti_cheat", kind=RunKind.ORACLE, scope=RunScope.ANTI_CHEAT,
            command=["sh", "/tests/test.sh", *[_target_arg(x) for x in lists.anti_cheat]],
            task_dir=task_dir, evidence_dir=evidence_dir, limits=limits,
            expected_ids=lists.anti_cheat, with_solution=True,
        ))

    # 9. repeat/base/full
    if repeat:
        runs.append(_execute_run(
            runner=runner, image=image, image_digest=image_digest,
            name="repeat/base/full", kind=RunKind.BASE, scope=RunScope.FULL,
            command=["sh", "/tests/test.sh"],
            task_dir=task_dir, evidence_dir=evidence_dir, limits=limits,
            expected_ids=all_ids, with_solution=False, repeat_of="base/full",
        ))

        # 10. repeat/oracle/full
        runs.append(_execute_run(
            runner=runner, image=image, image_digest=image_digest,
            name="repeat/oracle/full", kind=RunKind.ORACLE, scope=RunScope.FULL,
            command=["sh", "/tests/test.sh"],
            task_dir=task_dir, evidence_dir=evidence_dir, limits=limits,
            expected_ids=all_ids, with_solution=True, repeat_of="oracle/full",
        ))

    return runs


def run_mutants(
    task_dir: Path, evidence_dir: Path, image: str, lists: TestLists, limits: Limits,
    mutants: list[Mutant], *, image_digest: str | None = None, runner: DockerRunner | None = None,
) -> list[RunResult]:
    """Прогоняет каждого мутанта поверх oracle и проверяет, что reward равен 0 (мутант пойман)."""
    runner = runner or DockerRunner()
    runs: list[RunResult] = []
    all_ids = lists.all_ids()

    for mutant in mutants:
        name = f"mutant/{mutant.name}"
        run_res = _execute_run(
            runner=runner, image=image, image_digest=image_digest,
            name=name, kind=RunKind.MUTANT, scope=RunScope.FULL,
            command=["sh", "/tests/test.sh"],
            task_dir=task_dir, evidence_dir=evidence_dir, limits=limits,
            expected_ids=all_ids, with_solution=True, mutant_patch=mutant.patch,
        )
        runs.append(run_res)

    return runs

