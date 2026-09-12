from __future__ import annotations

import json
import subprocess
from pathlib import Path

from harness.contracts import Limits, Mutant, RunKind, RunResult, RunScope, TestLists, TestOutcome, TestReport
from harness.pytest_ids import canonical_test_id, split_test_id
from harness.verify.docker import DockerRunner, Mount
from harness.verify.junit import parse_junit, with_missing

# Прогон, который применяет эталонное решение и отдаёт получившийся репозиторий наружу.
# Из его результата строится дифф решения и hunk-revert мутанты.
APPLY_SOLUTION_RUN = "oracle/apply"
APPLY_SOLUTION_COMMAND = ["sh", "-c", "sh /solution/solve.sh && cp -a /app/repo/. /out/"]

# Хвост stderr в note: достаточно, чтобы понять причину, и не раздувает summary.json.
NOTE_LOG_TAIL = 300


# Применение мутанта-замены внутри контейнера. Требование «якорь ровно один раз» —
# то же, что у solve.sh: иначе замена попала бы не туда, куда рассчитывала модель.
# Ненулевой выход означает, что test.sh не запустится и reward не будет записан, —
# вердикт зачтёт такой мутант невалидным и отбросит, а не «пойманным».
MUTANT_APPLIER = """import json
from pathlib import Path

spec = json.loads(Path("/logs/mutant.json").read_text(encoding="utf-8"))
target = Path("/app/repo") / spec["file_path"]
if not target.is_file():
    raise SystemExit(f"mutant target not found: {target}")
content = target.read_text(encoding="utf-8")
count = content.count(spec["anchor"])
if count != 1:
    raise SystemExit(f"anchor occurs {count} times in {spec['file_path']}, expected exactly 1")
target.write_text(content.replace(spec["anchor"], spec["replacement"], 1), encoding="utf-8")
"""


def _target_arg(test_id: str) -> str:
    """Преобразует 'tests/test_x.py::test_y' в '/tests/test_x.py::test_y' — путь в контейнере."""
    relative_path, test_name = split_test_id(test_id)
    if not test_name:
        return f"/tests/{relative_path}"
    return f"/tests/{relative_path}::{test_name}"


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
    mutant: Mutant | None = None,
) -> RunResult:
    run_log_dir = evidence_dir / name
    run_log_dir.mkdir(parents=True, exist_ok=True)

    mounts = [
        Mount(host=task_dir / "tests", container="/tests", read_only=True),
        Mount(host=run_log_dir, container="/logs", read_only=False),
    ]
    if with_solution or mutant is not None:
        mounts.append(Mount(host=task_dir / "solution", container="/solution", read_only=True))

    actual_cmd = command
    if mutant is not None and mutant.is_replacement:
        # Замену делает сам харнесс: скрипт и его данные кладём в log_dir (он же /logs).
        (run_log_dir / "mutant.json").write_text(
            json.dumps(
                {
                    "file_path": mutant.file_path,
                    "anchor": mutant.anchor,
                    "replacement": mutant.replacement,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (run_log_dir / "apply_mutant.py").write_text(MUTANT_APPLIER, encoding="utf-8")
        actual_cmd = [
            "sh", "-c",
            "sh /solution/solve.sh && python /logs/apply_mutant.py && sh /tests/test.sh",
        ]
    elif mutant is not None:
        # Пишем патч во временный файл внутри log_dir (который смонтирован как /logs)
        patch_file = run_log_dir / "mutant.patch"
        patch_file.write_text(mutant.patch, encoding="utf-8")
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


def _log_tail(path: Path, limit: int = NOTE_LOG_TAIL) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    return text[-limit:]


def run_apply_solution(
    task_dir: Path, evidence_dir: Path, image: str, limits: Limits, oracle_repo: Path,
    *, image_digest: str | None = None, runner: DockerRunner | None = None,
) -> RunResult:
    """Применяет solution/solve.sh в контейнере и выкладывает /app/repo в oracle_repo.

    Отсюда берётся дифф эталонного решения для hunk-revert мутантов. Скрипт пишет модель,
    поэтому исполняется он только в контейнере — с --network none и лимитами кейса, как любой
    другой прогон. На хосте у него было бы всё окружение харнесса вместе с токенами LLM
    (решение 2.4 плана).

    Прогон, который не дошёл до конца, возвращается с executed=False и причиной в note:
    молча отдать пустой список мутантов нельзя, мутационная проверка — основной критерий.
    """
    runner = runner or DockerRunner()
    run_log_dir = evidence_dir / APPLY_SOLUTION_RUN
    run_log_dir.mkdir(parents=True, exist_ok=True)
    oracle_repo.mkdir(parents=True, exist_ok=True)

    mounts = [
        Mount(host=task_dir / "solution", container="/solution", read_only=True),
        Mount(host=oracle_repo, container="/out", read_only=False),
    ]

    def _result(
        *, executed: bool, exit_code: int | None, duration_sec: float | None, note: str | None,
    ) -> RunResult:
        return RunResult(
            name=APPLY_SOLUTION_RUN,
            kind=RunKind.ORACLE,
            scope=RunScope.FULL,
            executed=executed,
            commands=[" ".join(APPLY_SOLUTION_COMMAND)],
            image_digest=image_digest,
            duration_sec=duration_sec,
            exit_code=exit_code,
            reward=None,
            report_path=None,
            log_dir=APPLY_SOLUTION_RUN,
            note=note,
        )

    try:
        outcome = runner.run(
            image=image,
            command=APPLY_SOLUTION_COMMAND,
            mounts=mounts,
            limits=limits,
            timeout_sec=limits.verifier_timeout_sec,
            log_dir=run_log_dir,
        )
    except (OSError, subprocess.SubprocessError) as error:
        # docker не установлен, демон не отвечает, права на сокет — причина должна быть видна.
        return _result(
            executed=False, exit_code=None, duration_sec=None,
            note=f"docker не запустился: {error}",
        )

    if outcome.timed_out:
        return _result(
            executed=False, exit_code=None, duration_sec=outcome.duration_sec,
            note=f"Timeout expired after {limits.verifier_timeout_sec}s",
        )
    if outcome.exit_code != 0:
        return _result(
            executed=False, exit_code=outcome.exit_code, duration_sec=outcome.duration_sec,
            note=f"solve.sh завершился с кодом {outcome.exit_code}: {_log_tail(outcome.stderr_path)}",
        )
    if not any(oracle_repo.iterdir()):
        return _result(
            executed=False, exit_code=outcome.exit_code, duration_sec=outcome.duration_sec,
            note="решение не выложило репозиторий в /out: папка пуста",
        )

    return _result(
        executed=True, exit_code=outcome.exit_code, duration_sec=outcome.duration_sec, note=None,
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
                # pytest печатает ID относительно --rootdir=/, но ведущий tests/ в выводе
                # то есть, то нет. Сверять с task.toml можно только в каноническом виде.
                collected_tests[canonical_test_id(line)] = TestReport(outcome=TestOutcome.PASSED)

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


LIST_SCOPES: tuple[tuple[str, RunScope], ...] = (
    ("fail_to_pass", RunScope.FAIL_TO_PASS),
    ("pass_to_pass", RunScope.PASS_TO_PASS),
    ("anti_cheat", RunScope.ANTI_CHEAT),
)


def run_full_pair(
    task_dir: Path, evidence_dir: Path, image: str, lists: TestLists, limits: Limits,
    *, image_digest: str | None = None, runner: DockerRunner | None = None,
) -> list[RunResult]:
    """base/full и oracle/full — полные прогоны до и после эталонного решения.

    Отделены от прогонов по спискам намеренно: именно их исходы решают, в каком списке
    тесту место (verdict.reclassify_by_outcomes), а прогоны по спискам должны идти уже
    по исправленной раскладке.
    """
    runner = runner or DockerRunner()
    all_ids = lists.all_ids()
    return [
        _execute_run(
            runner=runner, image=image, image_digest=image_digest,
            name="base/full", kind=RunKind.BASE, scope=RunScope.FULL,
            command=["sh", "/tests/test.sh"],
            task_dir=task_dir, evidence_dir=evidence_dir, limits=limits,
            expected_ids=all_ids, with_solution=False,
        ),
        _execute_run(
            runner=runner, image=image, image_digest=image_digest,
            name="oracle/full", kind=RunKind.ORACLE, scope=RunScope.FULL,
            command=["sh", "/tests/test.sh"],
            task_dir=task_dir, evidence_dir=evidence_dir, limits=limits,
            expected_ids=all_ids, with_solution=True,
        ),
    ]


def run_list_scopes(
    task_dir: Path, evidence_dir: Path, image: str, lists: TestLists, limits: Limits,
    *, image_digest: str | None = None, runner: DockerRunner | None = None,
) -> list[RunResult]:
    """Каждый из трёх списков отдельно, на исходном коде и на эталоне (PROTOCOL §5.6)."""
    runner = runner or DockerRunner()
    runs: list[RunResult] = []
    for kind, prefix, with_solution in (
        (RunKind.BASE, "base", False),
        (RunKind.ORACLE, "oracle", True),
    ):
        for list_name, scope in LIST_SCOPES:
            test_ids: list[str] = getattr(lists, list_name)
            if not test_ids:
                continue
            runs.append(_execute_run(
                runner=runner, image=image, image_digest=image_digest,
                name=f"{prefix}/{list_name}", kind=kind, scope=scope,
                command=["sh", "/tests/test.sh", *[_target_arg(x) for x in test_ids]],
                task_dir=task_dir, evidence_dir=evidence_dir, limits=limits,
                expected_ids=test_ids, with_solution=with_solution,
            ))
    return runs


def run_repeats(
    task_dir: Path, evidence_dir: Path, image: str, lists: TestLists, limits: Limits,
    *, image_digest: str | None = None, runner: DockerRunner | None = None,
) -> list[RunResult]:
    """Независимый повтор полных прогонов на свежих контейнерах (PROTOCOL §5.6)."""
    runner = runner or DockerRunner()
    all_ids = lists.all_ids()
    return [
        _execute_run(
            runner=runner, image=image, image_digest=image_digest,
            name="repeat/base/full", kind=RunKind.BASE, scope=RunScope.FULL,
            command=["sh", "/tests/test.sh"],
            task_dir=task_dir, evidence_dir=evidence_dir, limits=limits,
            expected_ids=all_ids, with_solution=False, repeat_of="base/full",
        ),
        _execute_run(
            runner=runner, image=image, image_digest=image_digest,
            name="repeat/oracle/full", kind=RunKind.ORACLE, scope=RunScope.FULL,
            command=["sh", "/tests/test.sh"],
            task_dir=task_dir, evidence_dir=evidence_dir, limits=limits,
            expected_ids=all_ids, with_solution=True, repeat_of="oracle/full",
        ),
    ]


def run_base_and_oracle(
    task_dir: Path, evidence_dir: Path, image: str, lists: TestLists, limits: Limits,
    *, repeat: bool = True, image_digest: str | None = None, runner: DockerRunner | None = None,
) -> list[RunResult]:
    """Вся матрица base и oracle одним вызовом: full, по спискам, повторы.

    verify_case вызывает фазы по отдельности, чтобы вклинить переклассификацию между
    полными прогонами и прогонами по спискам. Эта обёртка оставлена для прямых вызовов.
    """
    runner = runner or DockerRunner()
    kwargs = {"image_digest": image_digest, "runner": runner}
    runs = [
        *run_full_pair(task_dir, evidence_dir, image, lists, limits, **kwargs),
        *run_list_scopes(task_dir, evidence_dir, image, lists, limits, **kwargs),
    ]
    if repeat:
        runs += run_repeats(task_dir, evidence_dir, image, lists, limits, **kwargs)
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
            expected_ids=all_ids, with_solution=True, mutant=mutant,
        )
        runs.append(run_res)

    return runs

