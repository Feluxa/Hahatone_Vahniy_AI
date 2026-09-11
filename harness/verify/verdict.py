from __future__ import annotations

from harness.contracts import (
    Problem,
    ProblemCategory,
    RepairTarget,
    RunKind,
    RunResult,
    TestLists,
    TestOutcome,
    Verdict,
)


def decide(runs: list[RunResult], lists: TestLists, static_problems: list[Problem]) -> Verdict:
    """Анализирует результаты всех прогонов и статические проверки, формируя итоговый вердикт."""
    problems: list[Problem] = list(static_problems)

    # 1. Проверка дубликатов между списками
    dups = lists.duplicates()
    if dups:
        problems.append(Problem(
            category=ProblemCategory.LIST_MISMATCH,
            target=RepairTarget.TESTS,
            details=f"Duplicate test IDs across lists: {dups}",
            test_ids=dups,
        ))

    runs_by_name = {r.name: r for r in runs}

    # 2. Проверка сборки Dockerfile
    if "build" in runs_by_name:
        build_run = runs_by_name["build"]
        if not build_run.executed or build_run.exit_code != 0:
            problems.append(Problem(
                category=ProblemCategory.BUILD_FAILED,
                target=RepairTarget.ENVIRONMENT,
                details=f"Docker build failed with exit code {build_run.exit_code}: {build_run.note or ''}",
                run_names=["build"],
            ))

    # 3. Проверка collect-прогона
    if "collect" in runs_by_name:
        collect_run = runs_by_name["collect"]
        if collect_run.executed:
            collected_ids = set(collect_run.tests.keys())
            expected_set = set(lists.all_ids())
            if collected_ids != expected_set:
                diff_missing = sorted(expected_set - collected_ids)
                diff_extra = sorted(collected_ids - expected_set)
                details_parts = []
                if diff_missing:
                    details_parts.append(f"Missing: {diff_missing}")
                if diff_extra:
                    details_parts.append(f"Extra: {diff_extra}")
                problems.append(Problem(
                    category=ProblemCategory.LIST_MISMATCH,
                    target=RepairTarget.TESTS,
                    details=f"Collected tests do not match manifest lists: {'; '.join(details_parts)}",
                    test_ids=diff_missing + diff_extra,
                    run_names=["collect"],
                ))

    # 4. Проверка запрещенных маркеров (skip, xfail) во всех выполненных прогонах
    seen_skipped: set[str] = set()
    for r in runs:
        for t_id, rep in r.tests.items():
            if rep.outcome == TestOutcome.SKIPPED and t_id not in seen_skipped:
                seen_skipped.add(t_id)
                problems.append(Problem(
                    category=ProblemCategory.FORBIDDEN_MARKERS,
                    target=RepairTarget.TESTS,
                    details=f"Forbidden marker (skip/xfail) on test '{t_id}' in run {r.name}",
                    test_ids=[t_id],
                    run_names=[r.name],
                ))

    # 5. Проверка base/full
    if "base/full" in runs_by_name:
        base_run = runs_by_name["base/full"]
        if not base_run.executed:
            cat = ProblemCategory.TIMEOUT if base_run.note and "Timeout" in base_run.note else ProblemCategory.INTERNAL
            problems.append(Problem(
                category=cat,
                target=RepairTarget.ENVIRONMENT,
                details=f"base/full was not executed successfully: {base_run.note or 'non-zero exit code'}",
                run_names=["base/full"],
            ))
        else:
            if base_run.reward != 0:
                problems.append(Problem(
                    category=ProblemCategory.REWARD_WRONG,
                    target=RepairTarget.TESTS,
                    details=f"base/full reward is {base_run.reward}, expected 0",
                    run_names=["base/full"],
                ))

            # fail_to_pass должны падать строго по AssertionError
            for t_id in lists.fail_to_pass:
                rep = base_run.tests.get(t_id)
                if rep is None or rep.outcome == TestOutcome.MISSING:
                    problems.append(Problem(
                        category=ProblemCategory.LIST_MISMATCH,
                        target=RepairTarget.TESTS,
                        details=f"fail_to_pass test '{t_id}' missing in base/full",
                        test_ids=[t_id],
                        run_names=["base/full"],
                    ))
                elif rep.outcome == TestOutcome.PASSED:
                    problems.append(Problem(
                        category=ProblemCategory.BASE_F2P_PASSED,
                        target=RepairTarget.TESTS,
                        details=f"Defect not reproduced: fail_to_pass test '{t_id}' passed on base",
                        test_ids=[t_id],
                        run_names=["base/full"],
                    ))
                elif not rep.failed_by_assertion:
                    problems.append(Problem(
                        category=ProblemCategory.BASE_NOT_ASSERTION,
                        target=RepairTarget.TESTS,
                        details=f"fail_to_pass test '{t_id}' failed with {rep.exception_type or rep.outcome}, not AssertionError: {rep.message}",
                        test_ids=[t_id],
                        run_names=["base/full"],
                    ))

            # pass_to_pass и anti_cheat обязаны проходить
            for t_id in lists.pass_to_pass + lists.anti_cheat:
                rep = base_run.tests.get(t_id)
                if rep is None or rep.outcome != TestOutcome.PASSED:
                    out = rep.outcome.value if rep else "missing"
                    msg = rep.message if rep else ""
                    problems.append(Problem(
                        category=ProblemCategory.BASE_GUARD_FAILED,
                        target=RepairTarget.TESTS,
                        details=f"Guard test '{t_id}' failed on base ({out}): {msg}",
                        test_ids=[t_id],
                        run_names=["base/full"],
                    ))

    # 6. Проверка oracle/full
    if "oracle/full" in runs_by_name:
        oracle_run = runs_by_name["oracle/full"]
        if not oracle_run.executed:
            cat = ProblemCategory.TIMEOUT if oracle_run.note and "Timeout" in oracle_run.note else ProblemCategory.INTERNAL
            problems.append(Problem(
                category=cat,
                target=RepairTarget.ENVIRONMENT,
                details=f"oracle/full was not executed successfully: {oracle_run.note or 'non-zero exit code'}",
                run_names=["oracle/full"],
            ))
        else:
            if oracle_run.reward != 1:
                problems.append(Problem(
                    category=ProblemCategory.REWARD_WRONG,
                    target=RepairTarget.SOLUTION,
                    details=f"oracle/full reward is {oracle_run.reward}, expected 1",
                    run_names=["oracle/full"],
                ))

            # Все тесты обязаны проходить на oracle
            for t_id in lists.all_ids():
                rep = oracle_run.tests.get(t_id)
                if rep is None or rep.outcome != TestOutcome.PASSED:
                    out = rep.outcome.value if rep else "missing"
                    msg = rep.message if rep else ""
                    problems.append(Problem(
                        category=ProblemCategory.ORACLE_FAILED,
                        target=RepairTarget.SOLUTION,
                        details=f"Test '{t_id}' did not pass on oracle ({out}): {msg}",
                        test_ids=[t_id],
                        run_names=["oracle/full"],
                    ))

    # 7. Проверка повторных прогонов (repeatability)
    for r in runs:
        if r.repeat_of and r.repeat_of in runs_by_name:
            orig = runs_by_name[r.repeat_of]
            if r.reward != orig.reward:
                problems.append(Problem(
                    category=ProblemCategory.NOT_REPRODUCIBLE,
                    target=RepairTarget.TESTS,
                    details=f"Repeat run {r.name} reward ({r.reward}) != original ({orig.reward})",
                    run_names=[r.name, orig.name],
                ))
            for t_id in lists.all_ids():
                rep_orig = orig.tests.get(t_id)
                rep_repeat = r.tests.get(t_id)
                out_orig = rep_orig.outcome if rep_orig else None
                out_repeat = rep_repeat.outcome if rep_repeat else None
                if out_orig != out_repeat:
                    problems.append(Problem(
                        category=ProblemCategory.NOT_REPRODUCIBLE,
                        target=RepairTarget.TESTS,
                        details=f"Repeat run {r.name} test '{t_id}' outcome {out_repeat} != original {out_orig}",
                        test_ids=[t_id],
                        run_names=[r.name, orig.name],
                    ))

    # 8. Проверка мутантов (все должны давать reward == 0)
    for r in runs:
        if r.kind == RunKind.MUTANT and r.executed:
            if r.reward == 1:
                problems.append(Problem(
                    category=ProblemCategory.MUTANT_SURVIVED,
                    target=RepairTarget.TESTS,
                    details=f"Mutant survived in {r.name}: tests gave reward=1",
                    run_names=[r.name],
                ))

    run_names = [r.name for r in runs]
    return Verdict(ok=len(problems) == 0, problems=problems, runs=run_names)

