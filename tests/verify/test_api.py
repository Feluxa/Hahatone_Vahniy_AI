"""Стыки verify_case: статические проверки и применение решения попадают в вердикт."""
import json
from pathlib import Path

import pytest

from harness.contracts import Limits, ProblemCategory
from harness.verify import api
from harness.verify.docker import BuildOutcome, ContainerOutcome

LIMITS = Limits(
    agent_timeout_sec=600,
    verifier_timeout_sec=60,
    build_timeout_sec=300,
    cpus=1.0,
    memory_mb=1024,
    storage_mb=2048,
)


class _FakeRunner:
    """Docker не запускается: прогоны отдают пустой результат, проверяется только обвязка."""

    def build(self, env_dir: Path, tag: str, *, timeout_sec: int, log_path: Path) -> BuildOutcome:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("fake build\n", encoding="utf-8")
        return BuildOutcome(
            ok=True, image_tag=tag, image_digest="sha256:fake", duration_sec=0.1, log_path=log_path,
        )

    def run(self, image, command, *, mounts, limits, timeout_sec, log_dir) -> ContainerOutcome:
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout = log_dir / "stdout.log"
        stderr = log_dir / "stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return ContainerOutcome(
            exit_code=0, timed_out=False, duration_sec=0.1,
            stdout_path=stdout, stderr_path=stderr, command=list(command),
        )

    def remove_image(self, tag: str) -> None:
        return None


def _write_task_dir(root: Path, *, instruction: str) -> Path:
    task_dir = root / "task"
    (task_dir / "environment").mkdir(parents=True)
    (task_dir / "tests").mkdir(parents=True)
    (task_dir / "solution").mkdir(parents=True)
    (task_dir / "instruction.md").write_text(instruction, encoding="utf-8")
    (task_dir / "task.toml").write_text(
        '[metadata]\n'
        'fail_to_pass = ["tests/test_x.py::test_bug"]\n'
        'pass_to_pass = []\n'
        'anti_cheat = []\n',
        encoding="utf-8",
    )
    return task_dir


def test_verify_case_reports_static_problems(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "DockerRunner", _FakeRunner)
    task_dir = _write_task_dir(tmp_path, instruction="Смотри tests/ для подробностей.")

    _runs, verdict = api.verify_case(task_dir, tmp_path / "evidence", LIMITS)

    assert ProblemCategory.INSTRUCTION_LEAK in [p.category for p in verdict.problems]


def test_verify_case_does_not_swallow_static_check_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Сбой внутри check_task_folder не должен молча отключать все статические проверки.

    Раньше except (..., AttributeError, TypeError) проглатывал такую ошибку, и кейс
    получал ready вообще без статического анализа task/.
    """
    monkeypatch.setattr(api, "DockerRunner", _FakeRunner)

    def _boom(task_dir: Path, lists) -> list:
        raise TypeError("check_task_folder got an unexpected keyword argument")

    monkeypatch.setattr(api, "check_task_folder", _boom)
    task_dir = _write_task_dir(tmp_path, instruction="Ничего лишнего.")

    with pytest.raises(TypeError):
        api.verify_case(task_dir, tmp_path / "evidence", LIMITS)


class _ApplyFailingRunner(_FakeRunner):
    """Контейнер применения решения падает; остальные прогоны отрабатывают как обычно."""

    def run(self, image, command, *, mounts, limits, timeout_sec, log_dir) -> ContainerOutcome:
        outcome = super().run(image, command, mounts=mounts, limits=limits,
                              timeout_sec=timeout_sec, log_dir=log_dir)
        if any(m.container == "/out" for m in mounts):
            outcome.stderr_path.write_text("solve.sh: target file does not exist\n", encoding="utf-8")
            return ContainerOutcome(
                exit_code=1, timed_out=False, duration_sec=outcome.duration_sec,
                stdout_path=outcome.stdout_path, stderr_path=outcome.stderr_path,
                command=outcome.command,
            )
        return outcome


def test_verify_case_surfaces_failed_solution_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Мутантов нет — значит есть проблема в вердикте и запись в summary.json."""
    monkeypatch.setattr(api, "DockerRunner", _ApplyFailingRunner)
    task_dir = _write_task_dir(tmp_path, instruction="Ничего лишнего.")
    evidence_dir = tmp_path / "evidence"

    runs, verdict = api.verify_case(task_dir, evidence_dir, LIMITS)

    apply_run = next(r for r in runs if r.name == "oracle/apply")
    assert apply_run.executed is False
    assert "solve.sh завершился с кодом 1" in (apply_run.note or "")
    assert not any(r.name.startswith("mutant/") for r in runs)

    assert verdict.ok is False
    assert any("hunk-мутанты не построены" in p.details for p in verdict.problems)

    summary = json.loads((evidence_dir / "summary.json").read_text(encoding="utf-8"))
    recorded = next(r for r in summary["runs"] if r["name"] == "oracle/apply")
    assert recorded["executed"] is False
    assert "solve.sh" in recorded["note"]


def test_verify_case_skips_apply_run_without_mutants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api, "DockerRunner", _FakeRunner)
    task_dir = _write_task_dir(tmp_path, instruction="Ничего лишнего.")

    runs, _verdict = api.verify_case(
        task_dir, tmp_path / "evidence", LIMITS, api.VerifyOptions(run_mutants=False),
    )

    assert not any(r.name == "oracle/apply" for r in runs)
