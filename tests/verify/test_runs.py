"""Применение эталонного решения и мутантов: только в контейнере."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from harness.contracts import Limits, Mutant, MutantSource, RunKind, RunResult, TestLists
from harness.verify.docker import ContainerOutcome
from harness.verify.runs import (
    APPLY_SOLUTION_RUN,
    MUTANT_APPLIER,
    _target_arg,
    run_apply_solution,
    run_collect,
    run_mutants,
)

LIMITS = Limits(
    agent_timeout_sec=600,
    verifier_timeout_sec=60,
    build_timeout_sec=300,
    cpus=1.0,
    memory_mb=1024,
    storage_mb=2048,
)


class _Runner:
    """Подменяет docker: запоминает вызов и отдаёт заданный исход."""

    def __init__(self, *, exit_code: int = 0, timed_out: bool = False,
                 error: Exception | None = None, produces: dict[str, str] | None = None) -> None:
        self.exit_code = exit_code
        self.timed_out = timed_out
        self.error = error
        self.produces = produces or {}
        self.calls: list[dict] = []

    def run(self, image, command, *, mounts, limits, timeout_sec, log_dir) -> ContainerOutcome:
        self.calls.append({
            "image": image, "command": list(command), "mounts": list(mounts),
            "limits": limits, "timeout_sec": timeout_sec,
        })
        if self.error is not None:
            raise self.error

        log_dir.mkdir(parents=True, exist_ok=True)
        stdout = log_dir / "stdout.log"
        stderr = log_dir / "stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("sed: can't read /app/repo/missing.py\n", encoding="utf-8")

        out_mount = next((m for m in mounts if m.container == "/out"), None)
        if out_mount is not None:
            for name, content in self.produces.items():
                target = out_mount.host / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

        return ContainerOutcome(
            exit_code=None if self.timed_out else self.exit_code,
            timed_out=self.timed_out,
            duration_sec=0.5,
            stdout_path=stdout,
            stderr_path=stderr,
            command=list(command),
        )


def _task_dir(root: Path) -> Path:
    task_dir = root / "task"
    (task_dir / "solution").mkdir(parents=True)
    (task_dir / "solution" / "solve.sh").write_bytes(b"#!/bin/sh\nset -eu\n")
    return task_dir


def _apply(root: Path, runner: _Runner):
    return run_apply_solution(
        task_dir=_task_dir(root),
        evidence_dir=root / "evidence",
        image="case-verifier:test",
        limits=LIMITS,
        oracle_repo=root / "oracle",
        image_digest="sha256:test",
        runner=runner,
    )


def test_apply_solution_runs_in_container_with_expected_mounts(tmp_path: Path) -> None:
    """Решение применяется внутри образа: /solution только на чтение, результат — в /out."""
    runner = _Runner(produces={"netting.py": "value = 2\n"})

    run = _apply(tmp_path, runner)

    assert run.executed is True
    assert run.name == APPLY_SOLUTION_RUN
    assert run.kind == RunKind.ORACLE
    assert (tmp_path / "oracle" / "netting.py").read_text(encoding="utf-8") == "value = 2\n"

    call = runner.calls[0]
    assert call["command"] == ["sh", "-c", "sh /solution/solve.sh && cp -a /app/repo/. /out/"]
    assert call["timeout_sec"] == LIMITS.verifier_timeout_sec
    assert call["limits"] is LIMITS
    mounts = {m.container: m for m in call["mounts"]}
    assert mounts["/solution"].read_only is True
    assert mounts["/out"].read_only is False
    assert mounts["/out"].host == tmp_path / "oracle"


def test_apply_solution_reports_docker_failure(tmp_path: Path) -> None:
    """docker недоступен — прогон не выполнен, причина в note, исключение наружу не летит."""
    runner = _Runner(error=FileNotFoundError(2, "No such file or directory: 'docker'"))

    run = _apply(tmp_path, runner)

    assert run.executed is False
    assert "docker не запустился" in (run.note or "")


def test_apply_solution_reports_nonzero_exit(tmp_path: Path) -> None:
    runner = _Runner(exit_code=1)

    run = _apply(tmp_path, runner)

    assert run.executed is False
    assert "solve.sh завершился с кодом 1" in (run.note or "")
    # В note попадает хвост stderr, чтобы причина была понятна из summary.json.
    assert "missing.py" in (run.note or "")


def test_apply_solution_reports_timeout(tmp_path: Path) -> None:
    runner = _Runner(timed_out=True)

    run = _apply(tmp_path, runner)

    assert run.executed is False
    assert "Timeout" in (run.note or "")


def test_apply_solution_reports_empty_output(tmp_path: Path) -> None:
    """Контейнер вышел с нулём, но ничего не выложил — молча считать это успехом нельзя."""
    runner = _Runner(exit_code=0, produces={})

    run = _apply(tmp_path, runner)

    assert run.executed is False
    assert "папка пуста" in (run.note or "")


@pytest.mark.parametrize("runner", [
    _Runner(exit_code=1),
    _Runner(timed_out=True),
    _Runner(error=OSError("docker daemon is not running")),
])
def test_apply_solution_never_raises(tmp_path: Path, runner: _Runner) -> None:
    run = _apply(tmp_path, runner)
    assert run.executed is False
    assert run.note


def test_target_arg_accepts_both_prefix_forms() -> None:
    """Путь для контейнера один и тот же, пришёл ID с tests/ или без."""
    assert _target_arg("tests/test_close.py::test_x") == "/tests/test_close.py::test_x"
    assert _target_arg("test_close.py::test_x") == "/tests/test_close.py::test_x"
    assert _target_arg("/tests/sql/test_close.py::test_x") == "/tests/sql/test_close.py::test_x"


class _CollectRunner(_Runner):
    """Отдаёт заранее заданный вывод pytest --collect-only."""

    def __init__(self, stdout: str) -> None:
        super().__init__()
        self.stdout = stdout

    def run(self, image, command, *, mounts, limits, timeout_sec, log_dir) -> ContainerOutcome:
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = log_dir / "stdout.log"
        stderr_path = log_dir / "stderr.log"
        stdout_path.write_text(self.stdout, encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return ContainerOutcome(
            exit_code=0, timed_out=False, duration_sec=0.2,
            stdout_path=stdout_path, stderr_path=stderr_path, command=list(command),
        )


def test_collect_ids_are_canonical(tmp_path: Path) -> None:
    """Собранные ID канонизируются: иначе сверка со списками task.toml разойдётся на префиксе."""
    runner = _CollectRunner(
        "tests/test_close.py::test_bug\n"
        "test_close.py::test_guard\n"
        "/tests/sql/test_close.py::test_sql\n"
        "\n3 tests collected in 0.04s\n"
    )

    run = run_collect(
        task_dir=_task_dir(tmp_path),
        evidence_dir=tmp_path / "evidence",
        image="case-verifier:test",
        limits=LIMITS,
        runner=runner,
    )

    assert set(run.tests) == {
        "tests/test_close.py::test_bug",
        "tests/test_close.py::test_guard",
        "tests/sql/test_close.py::test_sql",
    }


class _CapturingRunner(_Runner):
    """Запоминает команду и файлы, которые харнесс положил в /logs."""

    def run(self, image, command, *, mounts, limits, timeout_sec, log_dir) -> ContainerOutcome:
        outcome = super().run(image, command, mounts=mounts, limits=limits,
                              timeout_sec=timeout_sec, log_dir=log_dir)
        self.log_dir = log_dir
        return outcome


def _mutant_task_dir(root: Path) -> Path:
    task_dir = root / "task"
    (task_dir / "tests").mkdir(parents=True)
    (task_dir / "solution").mkdir(parents=True)
    (task_dir / "solution" / "solve.sh").write_bytes(b"#!/bin/sh\nset -eu\n")
    return task_dir


def _run_one_mutant(root: Path, mutant: Mutant, runner: _Runner) -> RunResult:
    lists = TestLists(fail_to_pass=["tests/test_x.py::test_bug"], pass_to_pass=[], anti_cheat=[])
    return run_mutants(
        task_dir=_mutant_task_dir(root),
        evidence_dir=root / "evidence",
        image="case-verifier:test",
        lists=lists,
        limits=LIMITS,
        mutants=[mutant],
        runner=runner,
    )[0]


def test_replacement_mutant_is_applied_by_the_harness(tmp_path: Path) -> None:
    """Замену делает харнесс: в контейнер уходит скрипт и данные, а не unified diff."""
    runner = _CapturingRunner()
    mutant = Mutant(
        name="llm-mutant-sign", source=MutantSource.LLM, description="знак",
        patch="",
        file_path="backend/NettingPolicy.py",
        anchor="net = purchases - refunds",
        replacement="net = purchases + refunds",
    )

    run = _run_one_mutant(tmp_path, mutant, runner)

    assert run.name == "mutant/llm-mutant-sign"
    command = runner.calls[0]["command"]
    assert command == [
        "sh", "-c",
        "sh /solution/solve.sh && python /logs/apply_mutant.py && sh /tests/test.sh",
    ]
    assert not (runner.log_dir / "mutant.patch").exists()

    spec = json.loads((runner.log_dir / "mutant.json").read_text(encoding="utf-8"))
    assert spec == {
        "file_path": "backend/NettingPolicy.py",
        "anchor": "net = purchases - refunds",
        "replacement": "net = purchases + refunds",
    }
    applier = (runner.log_dir / "apply_mutant.py").read_text(encoding="utf-8")
    compile(applier, "apply_mutant.py", "exec")
    assert "expected exactly 1" in applier


def test_hunk_revert_mutant_still_uses_patch(tmp_path: Path) -> None:
    runner = _CapturingRunner()
    mutant = Mutant(
        name="hunk-1", source=MutantSource.HUNK_REVERT, description="revert",
        patch="--- a/f\n+++ b/f\n@@ -1 +1 @@\n-new\n+old\n",
    )

    _run_one_mutant(tmp_path, mutant, runner)

    command = runner.calls[0]["command"]
    assert "patch -p1 -d /app/repo < /logs/mutant.patch" in command[2]
    assert (runner.log_dir / "mutant.patch").exists()
    assert not (runner.log_dir / "mutant.json").exists()


def test_applier_requires_exactly_one_anchor(tmp_path: Path) -> None:
    """Скрипт замены — обычный Python: проверяем его поведение напрямую."""
    repo = tmp_path / "app" / "repo"
    repo.mkdir(parents=True)
    (repo / "policy.py").write_text("net = a - b\nnet = a - b\n", encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "mutant.json").write_text(
        json.dumps({"file_path": "policy.py", "anchor": "net = a - b", "replacement": "net = a + b"}),
        encoding="utf-8",
    )
    script = MUTANT_APPLIER.replace('"/logs/', f'"{logs.as_posix()}/').replace(
        '"/app/repo"', f'"{repo.as_posix()}"'
    )
    script_path = tmp_path / "apply.py"
    script_path.write_text(script, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(script_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )

    assert result.returncode != 0
    assert "expected exactly 1" in result.stderr
    # Файл не тронут: мутант невалиден, а не применён наполовину.
    assert (repo / "policy.py").read_text(encoding="utf-8") == "net = a - b\nnet = a - b\n"


def test_applier_replaces_unique_anchor(tmp_path: Path) -> None:
    repo = tmp_path / "app" / "repo"
    repo.mkdir(parents=True)
    (repo / "policy.py").write_text("net = a - b\nother = 1\n", encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "mutant.json").write_text(
        json.dumps({"file_path": "policy.py", "anchor": "net = a - b", "replacement": "net = a + b"}),
        encoding="utf-8",
    )
    script = MUTANT_APPLIER.replace('"/logs/', f'"{logs.as_posix()}/').replace(
        '"/app/repo"', f'"{repo.as_posix()}"'
    )
    script_path = tmp_path / "apply.py"
    script_path.write_text(script, encoding="utf-8")

    result = subprocess.run([sys.executable, str(script_path)], stderr=subprocess.PIPE, text=True)

    assert result.returncode == 0, result.stderr
    assert (repo / "policy.py").read_text(encoding="utf-8") == "net = a + b\nother = 1\n"
