"""Оркестрация: отказ прогонов доезжает до limitations в result.json.

LLM и Docker не участвуют — все внешние шаги подменены.
"""
import json
from pathlib import Path

import pytest

from harness import pipeline
from harness.build.manifest import ManifestError
from harness.build.task_folder import TaskFolderError
from harness.llm.parsing import ParsingError
from harness.contracts import (
    Author,
    CaseDraft,
    CaseInput,
    CaseSpec,
    Difficulty,
    Language,
    Limits,
    Problem,
    ProblemCategory,
    RepairTarget,
    RepoContext,
    RunKind,
    RunProfile,
    RunResult,
    RunScope,
    Status,
    TestLists,
    Verdict,
)

SHA = "a" * 64

APPLY_FAILED = Problem(
    category=ProblemCategory.INTERNAL,
    target=RepairTarget.NONE,
    details="hunk-мутанты не построены: solve.sh завершился с кодом 1: sed: can't read",
    run_names=["oracle/apply"],
)


def _case(tmp_path: Path) -> CaseInput:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "main.py").write_text("value = 1\n", encoding="utf-8")
    return CaseInput(
        protocol_version="1.0",
        repository=repository,
        brief="Почини расчёт",
        output_dir=tmp_path / "out",
        case_id="team/case-001",
        difficulty=Difficulty.MEDIUM,
        language=Language.RU,
        source="team/case-001",
        team="team",
        author=Author(name="Участник", email="participant@example.org"),
        limits=Limits(
            agent_timeout_sec=1800, verifier_timeout_sec=300, build_timeout_sec=900,
            cpus=2, memory_mb=4096, storage_mb=10240,
        ),
        seed=1,
    )


def _stub_pipeline(monkeypatch: pytest.MonkeyPatch, *, verdict: Verdict, runs: list[RunResult]) -> None:
    profile = RunProfile(python_version="3.11", requirements_file=None)
    context = RepoContext(
        snapshot_sha256=SHA, brief="Почини расчёт", files=[], python_symbols=[],
        sql_objects=[], existing_tests=[], run_profile=profile,
    )
    spec = CaseSpec(
        goal="g", behavior=[], invariants=[], edge_cases=[],
        defect_hypothesis="d", bank_domain="Расчёты", description="desc",
    )
    lists = TestLists(fail_to_pass=["tests/test_x.py::test_bug"], pass_to_pass=[], anti_cheat=[])

    monkeypatch.setattr(pipeline, "LlmClient", lambda **kwargs: object())
    monkeypatch.setattr(pipeline, "compute_snapshot_sha256", lambda repo: SHA)
    monkeypatch.setattr(pipeline, "copy_clean", lambda src, dst: dst.mkdir(parents=True))
    monkeypatch.setattr(pipeline, "build_context", lambda repo, brief: context)
    monkeypatch.setattr(pipeline, "write_spec", lambda client, ctx: spec)
    monkeypatch.setattr(pipeline, "write_instruction", lambda client, spec, lang: "Задание")
    monkeypatch.setattr(
        pipeline, "write_tests",
        lambda client, ctx, spec: ({"test_x.py": "def test_bug(): ..."}, lists, ["DOCS/sentinel.txt"]),
    )
    monkeypatch.setattr(pipeline, "write_solution", lambda client, ctx, spec: {"solve.sh": "#!/bin/sh\n"})
    monkeypatch.setattr(pipeline, "write_mutants", lambda client, ctx, draft, text: [])
    monkeypatch.setattr(
        pipeline, "write_alternative_solutions", lambda client, ctx, draft, text: [],
    )
    monkeypatch.setattr(pipeline, "repair", lambda client, ctx, draft, verdict, logs: draft)

    def _write_task_folder(task_dir, case, draft, run_profile, workspace_repo) -> None:
        task_dir.mkdir(parents=True)
        (task_dir / "task.toml").write_text("schema_version = \"1.1\"\n", encoding="utf-8")

    monkeypatch.setattr(pipeline, "write_task_folder", _write_task_folder)

    def _verify_case(task_dir, evidence_dir, limits, options=None):
        evidence_dir.mkdir(parents=True, exist_ok=True)
        return runs, verdict

    monkeypatch.setattr(pipeline, "verify_case", _verify_case)


def test_failed_solution_apply_reaches_limitations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Отказ построения hunk-мутантов виден в result.json, а не только в логе."""
    apply_run = RunResult(
        name="oracle/apply", kind=RunKind.ORACLE, scope=RunScope.FULL, executed=False,
        commands=["sh -c sh /solution/solve.sh && cp -a /app/repo/. /out/"],
        image_digest="sha256:1", duration_sec=1.0, exit_code=1, reward=None,
        report_path=None, log_dir="oracle/apply",
        note="solve.sh завершился с кодом 1: sed: can't read",
    )
    _stub_pipeline(
        monkeypatch,
        verdict=Verdict(ok=False, problems=[APPLY_FAILED], runs=["oracle/apply"]),
        runs=[apply_run],
    )
    case = _case(tmp_path)

    result = pipeline.run(case)

    assert result.status is Status.FAILED
    assert any(line.startswith("hunk-мутанты не построены: ") for line in result.limitations)

    written = json.loads((case.output_dir / "result.json").read_text(encoding="utf-8"))
    assert written["status"] == "failed"
    assert any("hunk-мутанты не построены" in line for line in written["limitations"])


def test_clean_verdict_gives_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_pipeline(monkeypatch, verdict=Verdict(ok=True, problems=[], runs=[]), runs=[])
    case = _case(tmp_path)

    result = pipeline.run(case)

    assert result.status is Status.READY
    assert result.limitations == []
    assert result.input_snapshot_sha256 == SHA


def test_draft_is_built_without_touching_task_folder_for_mutants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Промпт мутантов больше не требует собранной папки кейса и применения solve.sh."""
    seen: list[str] = []

    def _write_mutants(client, ctx, draft: CaseDraft, text: str) -> list:
        seen.append(text)
        return []

    _stub_pipeline(monkeypatch, verdict=Verdict(ok=True, problems=[], runs=[]), runs=[])
    monkeypatch.setattr(pipeline, "write_mutants", _write_mutants)

    pipeline.run(_case(tmp_path))

    assert len(seen) == 1
    assert "solve.sh" in seen[0]


def test_draft_failure_is_one_bad_iteration_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TaskFolderError на первой итерации отправляет в ремонт, а не убивает прогон."""
    _stub_pipeline(monkeypatch, verdict=Verdict(ok=True, problems=[], runs=[]), runs=[])

    attempts: list[int] = []
    repaired: list[int] = []

    def _write_task_folder(task_dir, case, draft, run_profile, workspace_repo) -> None:
        attempts.append(1)
        if len(attempts) == 1:
            raise TaskFolderError(
                ["списки тестов ссылаются на файл, которого нет в черновике: "
                 "tests/test_settlement_close.py"]
            )
        task_dir.mkdir(parents=True)

    def _repair(client, ctx, draft, verdict, logs):
        repaired.append(1)
        # Ремонт видит, что чинить надо тесты.
        assert [p.target for p in verdict.problems] == [RepairTarget.TESTS]
        assert all("Черновик кейса не собрался" in p.details for p in verdict.problems)
        return draft

    monkeypatch.setattr(pipeline, "write_task_folder", _write_task_folder)
    monkeypatch.setattr(pipeline, "repair", _repair)

    result = pipeline.run(_case(tmp_path))

    assert len(attempts) == 2
    assert len(repaired) == 1
    assert result.status is Status.READY


def test_three_failed_iterations_end_in_failed_with_reasons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Исчерпан лимит итераций — status failed и понятные limitations, а не трейсбек."""
    _stub_pipeline(monkeypatch, verdict=Verdict(ok=True, problems=[], runs=[]), runs=[])

    def _always_broken(task_dir, case, draft, run_profile, workspace_repo) -> None:
        raise ManifestError(["fail_to_pass: список пуст, кейс без дефекта не собирается"])

    monkeypatch.setattr(pipeline, "write_task_folder", _always_broken)
    case = _case(tmp_path)

    result = pipeline.run(case)

    assert result.status is Status.FAILED
    assert any("Черновик кейса не собрался" in line for line in result.limitations)
    assert any("fail_to_pass" in line for line in result.limitations)
    assert any("итераций ремонта" in line for line in result.limitations)
    assert result.task_path is None

    written = json.loads((case.output_dir / "result.json").read_text(encoding="utf-8"))
    assert written["status"] == "failed"
    assert written["task_path"] is None


def test_parsing_error_from_repair_keeps_previous_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Сорвавшийся ремонт не роняет прогон: черновик остаётся прежним."""
    verdict = Verdict(
        ok=False,
        problems=[Problem(
            category=ProblemCategory.BASE_F2P_PASSED,
            target=RepairTarget.TESTS,
            details="дефект не воспроизводится",
        )],
        runs=["base/full"],
    )
    _stub_pipeline(monkeypatch, verdict=verdict, runs=[])

    def _boom(client, ctx, draft, verdict_, logs):
        raise ParsingError("Could not extract valid JSON from LLM response")

    monkeypatch.setattr(pipeline, "repair", _boom)

    result = pipeline.run(_case(tmp_path))

    assert result.status is Status.FAILED
    assert any("дефект не воспроизводится" in line for line in result.limitations)


def test_verdict_notes_reach_limitations_without_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Переклассификация — ограничение кейса, о котором надо сказать, но не провал."""
    note = (
        "тест tests/test_x.py::test_boundary перенесён в fail_to_pass по фактическим исходам: "
        "падает на исходном коде по assert и проходит после эталонного решения"
    )
    _stub_pipeline(
        monkeypatch,
        verdict=Verdict(ok=True, problems=[], runs=["base/full"], notes=[note]),
        runs=[],
    )
    case = _case(tmp_path)

    result = pipeline.run(case)

    assert result.status is Status.READY
    assert result.limitations == [note]

    written = json.loads((case.output_dir / "result.json").read_text(encoding="utf-8"))
    assert written["status"] == "ready"
    assert written["limitations"] == [note]


def test_repair_attempts_are_preserved_and_declared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Кейс, собравшийся со второй попытки, говорит об этом сам.

    Раньше evidence/ неудачной попытки удалялся целиком, а в limitations не попадало
    ничего: по папке кейса нельзя было отличить «собралось сразу» от «тесты переписывали».
    """
    failing = Verdict(
        ok=False,
        problems=[Problem(
            category=ProblemCategory.BASE_F2P_PASSED,
            target=RepairTarget.TESTS,
            details="Defect not reproduced: fail_to_pass test passed in base/full",
            test_ids=["tests/test_x.py::test_bug"],
        )],
        runs=["base/full"],
    )
    passing = Verdict(ok=True, problems=[], runs=["base/full"])

    _stub_pipeline(monkeypatch, verdict=passing, runs=[])

    verdicts = [failing, passing]
    attempts_seen: list[int] = []

    def _verify_case(task_dir, evidence_dir, limits, options=None):
        index = len(attempts_seen)
        attempts_seen.append(index)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "summary.json").write_text(
            json.dumps({"attempt": index}), encoding="utf-8",
        )
        return [], verdicts[index]

    monkeypatch.setattr(pipeline, "verify_case", _verify_case)

    case = _case(tmp_path)
    result = pipeline.run(case)

    assert result.status is Status.READY
    assert attempts_seen == [0, 1]

    evidence_dir = case.output_dir / "evidence"
    # Улики удачной попытки лежат на своём месте по протоколу.
    assert json.loads((evidence_dir / "summary.json").read_text(encoding="utf-8")) == {"attempt": 1}
    # Улики провальной — рядом, а не стёрты.
    saved = evidence_dir / "attempts" / "attempt-1" / "summary.json"
    assert json.loads(saved.read_text(encoding="utf-8")) == {"attempt": 0}
    # Временный каталог за собой не оставляем.
    assert not (case.output_dir / "evidence-attempts").exists()

    assert any("repair_iterations: 1" in note for note in result.limitations)
    assert any("попыток 2" in note for note in result.limitations)
    assert any(
        "base_f2p_passed" in note and "tests" in note for note in result.limitations
    )


def test_single_attempt_declares_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Кейс, собравшийся сразу, не обрастает разделом про ремонт и папкой attempts."""
    _stub_pipeline(monkeypatch, verdict=Verdict(ok=True, problems=[], runs=[]), runs=[])

    case = _case(tmp_path)
    result = pipeline.run(case)

    assert result.status is Status.READY
    assert result.limitations == []
    assert not (case.output_dir / "evidence" / "attempts").exists()
