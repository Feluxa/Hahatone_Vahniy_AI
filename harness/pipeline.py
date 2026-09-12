"""Оркестрация и repair loop. Владелец: №4.

input -> snapshot -> workspace -> context -> spec/instruction -> tests -> solution -> task/ -> static checks
-> verify_case -> (repair, максимум MAX_REPAIR_ITERATIONS) -> evidence -> snapshot again -> result.json
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from harness.contracts import (
    CaseDraft,
    CaseInput,
    CaseResult,
    Problem,
    ProblemCategory,
    RepairTarget,
    Status,
    UsageLog,
    Verdict,
)
from harness.repo.snapshot import compute_snapshot_sha256
from harness.repo.workspace import copy_clean
from harness.repo.context import build_context
from harness.llm.client import LlmClient
from harness.llm.spec_writer import write_spec, write_instruction
from harness.llm.test_writer import write_tests
from harness.llm.solution_writer import write_solution
from harness.llm.mutant_writer import write_mutants
from harness.llm.parsing import ParsingError
from harness.llm.repair import repair
from harness.build.manifest import ManifestError
from harness.build.task_folder import TaskFolderError, write_task_folder
from harness.verify.api import verify_case, VerifyOptions
from harness.evidence.usage import write_usage
from harness.protocol.output import write_result

MAX_REPAIR_ITERATIONS = 3
LOGGER = logging.getLogger(__name__)

# Черновик не удалось превратить в папку кейса: битые списки тестов, битый манифест,
# неразобранный ответ модели. Внутри цикла это неудачная итерация, а не конец прогона.
DRAFT_ERRORS = (TaskFolderError, ManifestError, ParsingError)


def _draft_failed_verdict(error: Exception) -> Verdict:
    """Вердикт за итерацию, которая не дошла до прогонов: чинить надо тесты."""
    problems = getattr(error, "problems", None) or [str(error)]
    return Verdict(
        ok=False,
        problems=[
            Problem(
                category=ProblemCategory.LIST_MISMATCH,
                target=RepairTarget.TESTS,
                details=f"Черновик кейса не собрался: {detail}",
            )
            for detail in problems
        ],
        runs=[],
    )


def _collect_log_excerpts(runs, evidence_dir: Path) -> dict[str, str]:
    """Собирает фрагменты логов для repair. Ищет pytest.log в правильном месте."""
    log_excerpts: dict[str, str] = {}
    for run_res in runs:
        if not run_res.executed:
            continue
        log_path = None
        if run_res.name == "build":
            log_path = evidence_dir / "build.log"
        elif run_res.log_dir:
            # test.sh пишет pytest.log в /logs/verifier/ → на хосте это log_dir/verifier/pytest.log
            candidate = evidence_dir / run_res.log_dir / "verifier" / "pytest.log"
            if candidate.exists():
                log_path = candidate
            else:
                # fallback: stdout контейнера
                stdout = evidence_dir / run_res.log_dir / "stdout.log"
                if stdout.exists():
                    log_path = stdout

        if log_path and log_path.exists():
            try:
                text = log_path.read_text(encoding="utf-8", errors="replace")
                # Передаём только хвост, чтобы не раздувать промпт
                if len(text) > 4000:
                    text = text[-4000:]
                log_excerpts[run_res.name] = text
            except OSError:
                pass
    return log_excerpts


def run(case: CaseInput) -> CaseResult:
    usage = UsageLog(calls=[])
    client = LlmClient(usage=usage)

    limitations: list[str] = []
    task_dir = case.output_dir / "task"
    evidence_dir = case.output_dir / "evidence"
    initial_sha: str | None = None
    workspace_repo: Path | None = None

    try:
        # 1. Snapshot — до любых действий
        initial_sha = compute_snapshot_sha256(case.repository)

        # 2. Workspace — временная рабочая копия (не внутри output_dir!)
        workspace_tmp = tempfile.mkdtemp(prefix="harness-ws-")
        workspace_repo = Path(workspace_tmp) / "repo"
        copy_clean(case.repository, workspace_repo)

        case.output_dir.mkdir(parents=True, exist_ok=True)

        # 3. Context
        context = build_context(workspace_repo, case.brief)

        # 4. Spec / Instruction
        spec = write_spec(client, context)
        instruction_md = write_instruction(client, spec, case.language)

        # 5. Tests
        test_files, test_lists, protected_files = write_tests(client, context, spec)

        # 6. Solution
        solution_files = write_solution(client, context, spec)

        draft = CaseDraft(
            spec=spec,
            instruction_md=instruction_md,
            test_files=test_files,
            lists=test_lists,
            solution_files=solution_files,
            protected_files=protected_files,
        )

        # 6.5. LLM-мутанты — генерируем один раз до цикла
        llm_mutants = []
        try:
            # Дифф эталонного решения существует только после применения solve.sh, а применяется
            # он в контейнере (verify.runs.run_apply_solution) — образа здесь ещё нет. Поэтому
            # модели показывается сам скрипт решения: anchor/replacement описывают изменение
            # не хуже диффа, и ничего исполнять на хосте для этого не нужно.
            solution_text = "\n\n".join(
                f"### {path}\n{content}"
                for path, content in sorted(draft.solution_files.items())
            )
            if solution_text.strip():
                llm_mutants = write_mutants(client, context, draft, solution_text)
                LOGGER.info("Generated %d LLM mutants", len(llm_mutants))
        except Exception:
            LOGGER.warning("LLM mutant generation failed, continuing with hunk-revert only",
                           exc_info=True)

        final_verdict = None
        verify_options = VerifyOptions(
            repeat=True,
            run_mutants=True,
            extra_mutants=llm_mutants,
        )

        for iteration in range(MAX_REPAIR_ITERATIONS + 1):
            if iteration > 0:
                LOGGER.info("Repair iteration %d / %d", iteration, MAX_REPAIR_ITERATIONS)

            # 7. (Re)write task folder
            if task_dir.exists():
                shutil.rmtree(task_dir)
            if evidence_dir.exists():
                shutil.rmtree(evidence_dir)

            # 8 & 9. verify_case (includes static checks, Docker runs, mutants).
            # Несобираемый черновик — это провал итерации, а не конец прогона: следующая
            # итерация ремонта получит проблему с target=tests и шанс её исправить.
            try:
                write_task_folder(task_dir, case, draft, context.run_profile, workspace_repo)
                runs, verdict = verify_case(task_dir, evidence_dir, case.limits, verify_options)
            except DRAFT_ERRORS as error:
                LOGGER.warning("Итерация %d: черновик не собрался: %s", iteration, error)
                runs = []
                verdict = _draft_failed_verdict(error)

            final_verdict = verdict

            if verdict.ok:
                break

            if iteration < MAX_REPAIR_ITERATIONS and verdict.problems:
                # 10. Repair — собираем логи и чиним. Ремонт, который сам не удался,
                # оставляет прежний рабочий черновик.
                log_excerpts = _collect_log_excerpts(runs, evidence_dir)
                try:
                    draft = repair(client, context, draft, verdict, log_excerpts)
                except DRAFT_ERRORS as error:
                    LOGGER.warning("Итерация %d: ремонт не удался: %s", iteration, error)
            else:
                break

        # 11. Evidence — usage
        write_usage(evidence_dir, usage)

        if final_verdict and final_verdict.notes:
            # Верификация что-то поправила сама (например, переложила тест между списками):
            # это ограничение кейса, о котором надо сказать, но не провал.
            limitations.extend(final_verdict.notes)

        if final_verdict and final_verdict.ok:
            status = Status.READY
        else:
            status = Status.FAILED
            limitations.append(
                f"Кейс не прошёл верификацию после {MAX_REPAIR_ITERATIONS} итераций ремонта"
            )
            if final_verdict and final_verdict.problems:
                limitations.extend([p.details for p in final_verdict.problems])

        # 12. Snapshot again — исходник не изменён
        final_sha = compute_snapshot_sha256(case.repository)
        if initial_sha != final_sha:
            status = Status.FAILED
            limitations.append("Исходный репозиторий был изменён в процессе работы")

        result = CaseResult(
            protocol_version=case.protocol_version,
            case_id=case.case_id,
            status=status,
            task_path="task" if task_dir.exists() else None,
            evidence_path="evidence" if evidence_dir.exists() else None,
            limitations=limitations,
            input_snapshot_sha256=final_sha,
        )

    except Exception as e:
        LOGGER.exception("Pipeline failed")
        err_msg = str(e) or repr(e) or e.__class__.__name__
        limitations.append(err_msg)

        # Пишем usage даже при ошибке — LLM-вызовы уже потрачены
        try:
            evidence_dir.mkdir(parents=True, exist_ok=True)
            write_usage(evidence_dir, usage)
        except Exception:
            LOGGER.warning("Failed to write usage on error path", exc_info=True)

        result = CaseResult(
            protocol_version=case.protocol_version,
            case_id=case.case_id,
            status=Status.FAILED,
            task_path="task" if task_dir.exists() else None,
            evidence_path="evidence" if evidence_dir.exists() else None,
            limitations=limitations,
            input_snapshot_sha256=initial_sha,
        )

    finally:
        # Очистка workspace — он не должен оставаться в output_dir
        if workspace_repo is not None:
            workspace_root = workspace_repo.parent
            shutil.rmtree(workspace_root, ignore_errors=True)

    # 13. result.json
    write_result(case.output_dir, result)
    return result
