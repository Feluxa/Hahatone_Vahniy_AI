from __future__ import annotations

import logging

from harness.contracts import (
    Problem,
    ProblemCategory,
    RepairTarget,
    RunKind,
    RunResult,
    TestLists,
    TestOutcome,
    TestReport,
    Verdict,
)
from harness.verify.runs import APPLY_SOLUTION_RUN

LOGGER = logging.getLogger(__name__)

# Имя, которое mutant_writer._sanitize_name гарантирует каждому мутанту от модели.
# Всё остальное в mutant/* — наши hunk-revert мутанты из diff эталонного решения.
LLM_MUTANT_PREFIX = "mutant/llm-mutant-"

# Альтернативное корректное решение: тот же прогон замены, но ожидание обратное —
# тесты обязаны его ПРИНЯТЬ (reward 1). Префикс ставит mutant_writer._sanitize_alt_name.
ALT_SOLUTION_PREFIX = "mutant/alt-solution-"

# Прогоны по спискам (PROTOCOL §5.6: каждый список проверяется отдельно на base и oracle).
# Имена задаёт runs.run_base_and_oracle; отсутствующий прогон означает пустой список.
BASE_LIST_RUNS: dict[str, str] = {
    "base/fail_to_pass": "fail_to_pass",
    "base/pass_to_pass": "pass_to_pass",
    "base/anti_cheat": "anti_cheat",
}
ORACLE_LIST_RUNS: dict[str, str] = {
    "oracle/fail_to_pass": "fail_to_pass",
    "oracle/pass_to_pass": "pass_to_pass",
    "oracle/anti_cheat": "anti_cheat",
}

# Ожидаемый reward каждого прогона. test.sh пишет 1, когда все собранные тесты прошли,
# поэтому reward зависит не от того, base это или oracle, а от того, обязаны ли падать
# тесты запущенного списка. На исходном коде падают только fail_to_pass; pass_to_pass и
# anti_cheat обязаны проходить и до решения, значит в своих прогонах дают 1.
EXPECTED_REWARD: dict[str, int] = {
    "base/full": 0,
    "base/fail_to_pass": 0,
    "base/pass_to_pass": 1,
    "base/anti_cheat": 1,
    "oracle/full": 1,
    "oracle/fail_to_pass": 1,
    "oracle/pass_to_pass": 1,
    "oracle/anti_cheat": 1,
}


def reclassify_by_outcomes(
    lists: TestLists, runs: list[RunResult],
) -> tuple[TestLists, list[str]]:
    """Раскладывает тесты по спискам по фактическим исходам base/full и oracle/full.

    Модель ошибается в классификации чаще, чем в самих тестах: корректный тест, который ловит
    ровно тот дефект, ради которого кейс и собирается, регулярно оказывается в pass_to_pass,
    и кейс не может стать валидным. Исходы прогонов знают правду, поэтому решает не декларация,
    а факт: упал на base по assert и прошёл на oracle — это fail_to_pass.

    Не перекладываются:
      * тесты, падающие на oracle, — это проблема решения или теста, её чинит ремонт;
      * тесты, падающие на base не по assert (ошибка импорта, фикстуры, окружения), —
        такое падение не заменяет проверку дефекта (PROTOCOL §5.4);
      * тесты, проходящие и на base, и на oracle, — они на своём месте.

    Возвращает новые списки и строки для Verdict.notes. Пустой список строк означает,
    что ничего менять не пришлось.
    """
    runs_by_name = {r.name: r for r in runs}
    base_run = runs_by_name.get("base/full")
    oracle_run = runs_by_name.get("oracle/full")
    if base_run is None or oracle_run is None or not base_run.executed or not oracle_run.executed:
        # Без обоих полных прогонов фактических исходов нет, и гадать нельзя.
        return lists, []

    moved: list[str] = []
    notes: list[str] = []
    for test_id in [*lists.pass_to_pass, *lists.anti_cheat]:
        base_report = base_run.tests.get(test_id)
        oracle_report = oracle_run.tests.get(test_id)
        if base_report is None or oracle_report is None:
            continue
        if not base_report.failed_by_assertion:
            continue
        if oracle_report.outcome != TestOutcome.PASSED:
            continue
        moved.append(test_id)
        notes.append(
            f"тест {test_id} перенесён в fail_to_pass по фактическим исходам: "
            f"падает на исходном коде по assert и проходит после эталонного решения"
        )
        LOGGER.info("Переклассификация: %s -> fail_to_pass", test_id)

    if not moved:
        return lists, []

    moved_set = set(moved)
    return (
        TestLists(
            fail_to_pass=[*lists.fail_to_pass, *moved],
            pass_to_pass=[t for t in lists.pass_to_pass if t not in moved_set],
            anti_cheat=[t for t in lists.anti_cheat if t not in moved_set],
        ),
        notes,
    )


def invalid_tests(runs: list[RunResult]) -> dict[str, TestReport]:
    """Тесты, которые невалидны сами по себе, а не ловят дефект продукта.

    Признак: один и тот же тест падает и на исходном коде, и на эталоне с одним и тем же
    исключением, и это не AssertionError. Продукт между прогонами меняется, исключение — нет,
    значит дело не в нём: неверные входные данные, несуществующее поле, недопустимое значение
    ограниченного домена.

    Различать это обязательно: иначе тот же случай приходит в ремонт как ORACLE_FAILED плюс
    BASE_GUARD_FAILED плюс «reward is 0», читается как «сломан продукт», и ремонт итерацию
    за итерацией правит solve.sh вместо теста.
    """
    seen: dict[RunKind, dict[str, dict[str, TestReport]]] = {RunKind.BASE: {}, RunKind.ORACLE: {}}
    for run in runs:
        bucket = seen.get(run.kind)
        if bucket is None or not run.executed:
            continue
        for test_id, report in run.tests.items():
            exception_type = report.exception_type
            if not exception_type or exception_type == "AssertionError":
                continue
            if report.outcome not in (TestOutcome.FAILED, TestOutcome.ERROR):
                continue
            bucket.setdefault(test_id, {}).setdefault(exception_type, report)

    invalid: dict[str, TestReport] = {}
    for test_id, base_types in seen[RunKind.BASE].items():
        shared = sorted(set(base_types) & set(seen[RunKind.ORACLE].get(test_id, {})))
        if shared:
            invalid[test_id] = base_types[shared[0]]
    return invalid


def _invalid_test_problem(test_id: str, report: TestReport) -> Problem:
    return Problem(
        category=ProblemCategory.TEST_INVALID,
        target=RepairTarget.TESTS,
        details=(
            f"Тест {test_id} падает одинаково на исходном коде и на эталоне: "
            f"{report.exception_type}: {report.message}. "
            f"Продукт тут ни при чём — невалиден сам тест (неверные входные данные, "
            f"несуществующее поле или недопустимое значение). Исправь тест, не решение."
        ),
        test_ids=[test_id],
    )


def _touches_invalid(run: RunResult, skip: set[str]) -> bool:
    """Прогон, в котором участвовал невалидный тест: его reward ничего не говорит о продукте."""
    return any(test_id in skip for test_id in run.tests)


SYNTAX_OR_IMPORT_ERRORS = {
    "SyntaxError",
    "IndentationError",
    "TabError",
    "ImportError",
    "ModuleNotFoundError",
}


def _is_syntax_or_import_breaker(run: RunResult) -> bool:
    """Мутант не дошёл до проверок тестов: упали сборка, импорт или сбор pytest.

    reward 0 у такого прогона выставлен парсером или импортом, а не тестами, поэтому
    засчитывать мутанта пойманным нельзя (PROTOCOL §5.4: ошибка импорта или окружения
    не заменяет проверку дефекта).

    Признака два, и нужны оба:

    1. Структурный — ни один ожидаемый тест не дошёл до вердикта: нет ни PASSED, ни FAILED,
       всё в ERROR, MISSING или SKIPPED. Это единственный признак, который работает при
       сломанном сборе: pytest пишет туда <error message="collection failure"> без типа
       исключения, а ожидаемые тесты становятся MISSING вообще без сообщения.
    2. По типу исключения — среди ошибок есть SyntaxError, ImportError и подобные. Ловит
       случай, когда часть тестов всё же отработала, а модуль репозитория не импортировался.

    Только на второй признак полагаться нельзя: тип исключения у <error> восстанавливается
    из текста трейсбека эвристикой (junit._exception_type_from_error) и может не найтись.
    """
    if not run.tests:
        return True

    if any(
        (rep.exception_type or "") in SYNTAX_OR_IMPORT_ERRORS
        for rep in run.tests.values()
        if rep.outcome in (TestOutcome.ERROR, TestOutcome.MISSING)
    ):
        return True

    outcomes = {rep.outcome for rep in run.tests.values()}
    return not (outcomes & {TestOutcome.FAILED, TestOutcome.PASSED})


def _check_alternative_solution(
    run: RunResult, problems: list[Problem], checked: list[str],
) -> None:
    """Альтернативное корректное решение обязано ПРОЙТИ тесты (PROTOCOL §5.7).

    Мутанты проверяют только одну сторону — что неправильное решение отвергается. Тесты,
    переобученные на конкретный дифф эталона, эту сторону проходят полностью и всё равно
    наказывают агента за корректную реализацию, написанную иначе.

    Прогон, который не дошёл до тестов (патч не применился, сломался сбор), ничего не
    доказывает ни за, ни против: винить в этом тесты нельзя, поэтому проблема не заводится,
    а отсутствие проверки уезжает в limitations отдельной нотой.
    """
    if not run.executed or run.reward is None:
        LOGGER.info(
            "Альтернативное решение %s не проверено: прогон не дошёл до тестов (executed=%s, note=%s)",
            run.name, run.executed, run.note,
        )
        return

    if run.reward == 1:
        checked.append(run.name)
        return

    if _is_syntax_or_import_breaker(run):
        # Сломался сам вариант, а не тесты: отвергать нечего, проверка не состоялась.
        LOGGER.warning(
            "Альтернативное решение %s не проверено: вызвало сбой импорта/синтаксиса", run.name,
        )
        return

    failed = sorted(
        test_id for test_id, report in run.tests.items()
        if report.outcome in (TestOutcome.FAILED, TestOutcome.ERROR)
    )
    checked.append(run.name)
    problems.append(Problem(
        category=ProblemCategory.ALTERNATIVE_SOLUTION_FAILED,
        target=RepairTarget.TESTS,
        details=(
            f"Альтернативное корректное решение {run.name} отвергнуто тестами (reward=0). "
            f"Не прошли: {', '.join(failed) if failed else 'список тестов не разобран'}. "
            f"Проверка привязана к тексту эталонного решения, а не к его поведению "
            f"(PROTOCOL §5.7). Ослабь проверку до наблюдаемого результата, не удаляя её "
            f"и не снижая строгости к неправильным решениям."
        ),
        test_ids=failed,
        run_names=[run.name],
    ))


def _check_executed(
    run: RunResult, problems: list[Problem], *, target: RepairTarget = RepairTarget.ENVIRONMENT,
) -> bool:
    """Невыполненный прогон никогда не считается успешным (PROTOCOL §2)."""
    if run.executed:
        return True
    category = (
        ProblemCategory.TIMEOUT
        if run.note and "Timeout" in run.note
        else ProblemCategory.INTERNAL
    )
    problems.append(Problem(
        category=category,
        target=target,
        details=f"{run.name} was not executed successfully: {run.note or 'non-zero exit code'}",
        run_names=[run.name],
    ))
    return False


def _check_reward(run: RunResult, expected: int, problems: list[Problem], target: RepairTarget) -> None:
    if run.reward != expected:
        problems.append(Problem(
            category=ProblemCategory.REWARD_WRONG,
            target=target,
            details=f"{run.name} reward is {run.reward}, expected {expected}",
            run_names=[run.name],
        ))


def _check_fail_to_pass(
    run: RunResult, test_ids: list[str], problems: list[Problem], skip: set[str],
) -> None:
    """На исходном коде каждый fail_to_pass обязан падать, и именно по assert."""
    for test_id in test_ids:
        if test_id in skip:
            continue
        report = run.tests.get(test_id)
        if report is None or report.outcome == TestOutcome.MISSING:
            problems.append(Problem(
                category=ProblemCategory.LIST_MISMATCH,
                target=RepairTarget.TESTS,
                details=f"fail_to_pass test '{test_id}' missing in {run.name}",
                test_ids=[test_id],
                run_names=[run.name],
            ))
        elif report.outcome == TestOutcome.PASSED:
            problems.append(Problem(
                category=ProblemCategory.BASE_F2P_PASSED,
                target=RepairTarget.TESTS,
                details=f"Defect not reproduced: fail_to_pass test '{test_id}' passed in {run.name}",
                test_ids=[test_id],
                run_names=[run.name],
            ))
        elif not report.failed_by_assertion:
            problems.append(Problem(
                category=ProblemCategory.BASE_NOT_ASSERTION,
                target=RepairTarget.TESTS,
                details=(
                    f"fail_to_pass test '{test_id}' failed in {run.name} with "
                    f"{report.exception_type or 'unrecognised exception'}, "
                    f"not AssertionError: {report.message}"
                ),
                test_ids=[test_id],
                run_names=[run.name],
            ))


def _check_all_passed(
    run: RunResult, test_ids: list[str], problems: list[Problem], *,
    category: ProblemCategory, target: RepairTarget, skip: set[str],
) -> None:
    for test_id in test_ids:
        if test_id in skip:
            continue
        report = run.tests.get(test_id)
        if report is None or report.outcome != TestOutcome.PASSED:
            outcome = report.outcome.value if report else "missing"
            message = report.message if report else ""
            problems.append(Problem(
                category=category,
                target=target,
                details=f"Test '{test_id}' did not pass in {run.name} ({outcome}): {message}",
                test_ids=[test_id],
                run_names=[run.name],
            ))


def decide(
    runs: list[RunResult], lists: TestLists, static_problems: list[Problem],
    *, notes: list[str] | None = None,
) -> Verdict:
    """Анализирует результаты всех прогонов и статические проверки, формируя итоговый вердикт."""
    problems: list[Problem] = list(static_problems)

    # 0. Тесты, невалидные сами по себе. Диагноз ставится первым и вытесняет остальные:
    # ORACLE_FAILED, BASE_GUARD_FAILED и «reward is N» по такому тесту увели бы ремонт
    # в solve.sh, хотя чинить надо тест.
    broken = invalid_tests(runs)
    for test_id, report in broken.items():
        problems.append(_invalid_test_problem(test_id, report))
    skip = set(broken)

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

    # 3. Проверка collect-прогона. Если он не выполнился, сверка «собранные ID = объединение
    # трёх списков» (PROTOCOL §4) просто не состоялась, и считать её пройденной нельзя:
    # упавший pytest --collect-only почти всегда означает, что файл тестов не импортируется.
    if "collect" in runs_by_name:
        collect_run = runs_by_name["collect"]
        if not collect_run.executed:
            problems.append(Problem(
                category=ProblemCategory.LIST_MISMATCH,
                target=RepairTarget.TESTS,
                details=(
                    "Сборка тестов не прошла, собранные тесты не сверены со списками манифеста. "
                    f"{collect_run.note or f'exit_code={collect_run.exit_code}'}"
                ),
                run_names=["collect"],
            ))
        else:
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
        if _check_executed(base_run, problems):
            if not _touches_invalid(base_run, skip):
                _check_reward(base_run, EXPECTED_REWARD["base/full"], problems, RepairTarget.TESTS)
            _check_fail_to_pass(base_run, lists.fail_to_pass, problems, skip)
            _check_all_passed(
                base_run, lists.pass_to_pass + lists.anti_cheat, problems,
                category=ProblemCategory.BASE_GUARD_FAILED, target=RepairTarget.TESTS,
                skip=skip,
            )

    # 5a. Проверка base по каждому списку отдельно (PROTOCOL §5.6)
    for run_name, list_name in BASE_LIST_RUNS.items():
        list_run = runs_by_name.get(run_name)
        if list_run is None or not _check_executed(list_run, problems):
            continue
        if not _touches_invalid(list_run, skip):
            _check_reward(list_run, EXPECTED_REWARD[run_name], problems, RepairTarget.TESTS)
        test_ids: list[str] = getattr(lists, list_name)
        if list_name == "fail_to_pass":
            _check_fail_to_pass(list_run, test_ids, problems, skip)
        else:
            _check_all_passed(
                list_run, test_ids, problems,
                category=ProblemCategory.BASE_GUARD_FAILED, target=RepairTarget.TESTS,
                skip=skip,
            )

    # 6. Проверка oracle/full
    if "oracle/full" in runs_by_name:
        oracle_run = runs_by_name["oracle/full"]
        if _check_executed(oracle_run, problems):
            if not _touches_invalid(oracle_run, skip):
                _check_reward(
                    oracle_run, EXPECTED_REWARD["oracle/full"], problems, RepairTarget.SOLUTION,
                )
            _check_all_passed(
                oracle_run, lists.all_ids(), problems,
                category=ProblemCategory.ORACLE_FAILED, target=RepairTarget.SOLUTION,
                skip=skip,
            )

    # 6a. Проверка oracle по каждому списку отдельно (PROTOCOL §5.6)
    for run_name, list_name in ORACLE_LIST_RUNS.items():
        list_run = runs_by_name.get(run_name)
        if list_run is None or not _check_executed(list_run, problems, target=RepairTarget.SOLUTION):
            continue
        if not _touches_invalid(list_run, skip):
            _check_reward(list_run, EXPECTED_REWARD[run_name], problems, RepairTarget.SOLUTION)
        _check_all_passed(
            list_run, getattr(lists, list_name), problems,
            category=ProblemCategory.ORACLE_FAILED, target=RepairTarget.SOLUTION,
            skip=skip,
        )

    # 6b. Применение решения для мутантов. Пустой список hunk-мутантов из-за сбоя контейнера
    # недопустим: мутационная проверка — основной критерий приёмки, её отказ обязан быть виден
    # и в summary.json, и в limitations результата.
    if APPLY_SOLUTION_RUN in runs_by_name:
        apply_run = runs_by_name[APPLY_SOLUTION_RUN]
        if not apply_run.executed:
            category = (
                ProblemCategory.TIMEOUT
                if apply_run.note and "Timeout" in apply_run.note
                else ProblemCategory.INTERNAL
            )
            problems.append(Problem(
                category=category,
                target=RepairTarget.NONE,
                details=f"hunk-мутанты не построены: {apply_run.note or 'решение не применилось'}",
                run_names=[APPLY_SOLUTION_RUN],
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

    # 8. Проверка мутантов. Пойманным считается только прогон, который дошёл до конца
    # и записал reward 0 в результате реальной проверки тестов (AssertionError),
    # а не из-за сломанного синтаксиса или сбоя импорта (PROTOCOL §5.4).
    valid_independent_mutants: list[str] = []
    has_mutant_runs = False
    alternatives_checked: list[str] = []
    notes_list = list(notes or [])

    for r in runs:
        if r.kind != RunKind.MUTANT:
            continue

        if r.name.startswith(ALT_SOLUTION_PREFIX):
            _check_alternative_solution(r, problems, alternatives_checked)
            continue

        has_mutant_runs = True
        if r.executed and r.reward == 0:
            if _is_syntax_or_import_breaker(r):
                if r.name.startswith(LLM_MUTANT_PREFIX):
                    LOGGER.warning(
                        "Мутант %s отброшен: вызвал синтаксическую ошибку или сбой импорта вместо логической проверки",
                        r.name,
                    )
                    discard_msg = f"Мутант {r.name} отброшен: вызвал сбой импорта/синтаксиса"
                    if discard_msg not in notes_list:
                        notes_list.append(discard_msg)
                else:
                    problems.append(Problem(
                        category=ProblemCategory.INTERNAL,
                        target=RepairTarget.NONE,
                        details=(
                            f"Hunk-revert мутант {r.name} вызвал сбой синтаксиса/импорта вместо логической проверки"
                        ),
                        run_names=[r.name],
                    ))
                continue

            if r.name.startswith(LLM_MUTANT_PREFIX):
                valid_independent_mutants.append(r.name)
            continue

        if r.executed and r.reward == 1:
            problems.append(Problem(
                category=ProblemCategory.MUTANT_SURVIVED,
                target=RepairTarget.TESTS,
                details=f"Mutant survived in {r.name}: tests gave reward=1",
                run_names=[r.name],
            ))
        elif r.name.startswith(LLM_MUTANT_PREFIX):
            # Невалидный патч от модели отбрасывается и не засчитывается (план §5.10).
            LOGGER.info("Мутант %s не дал reward, патч считается невалидным и отброшен", r.name)
        else:
            # Hunk-revert строится из нашего же диффа: не применился — сломан дифф или solve.sh.
            problems.append(Problem(
                category=ProblemCategory.INTERNAL,
                target=RepairTarget.NONE,
                details=(
                    f"Mutant {r.name} produced no reward "
                    f"(executed={r.executed}, exit_code={r.exit_code}, note={r.note}): "
                    f"патч не применился или test.sh не отработал, мутант не проверен"
                ),
                run_names=[r.name],
            ))

    # Если проводились прогоны мутантов, но ни один независимый мутант не пойман/не уцелел —
    # честно фиксируем это в notes (уезжает в limitations), чтобы не маскировать отсутствие сигнала.
    if has_mutant_runs and not valid_independent_mutants:
        missing_note = (
            "Мутационное тестирование проведено только на основе hunk-revert; "
            "независимые LLM-мутанты отсутствуют или были отброшены"
        )
        if missing_note not in notes_list:
            notes_list.append(missing_note)

    # Вторая сторона проверки (PROTOCOL §5.7): тесты обязаны принимать альтернативные
    # корректные реализации. Если проверить это не удалось, кейс валиден, но доказано
    # им меньше — и молчать об этом нельзя.
    if has_mutant_runs and not alternatives_checked:
        no_alt_note = (
            "Проверка на альтернативное корректное решение не проводилась: вариант "
            "не сгенерирован, не применился или сломал сборку. Тесты не доказали, что "
            "проверяют поведение, а не конкретный дифф эталона"
        )
        if no_alt_note not in notes_list:
            notes_list.append(no_alt_note)

    run_names = [r.name for r in runs]
    return Verdict(
        ok=len(problems) == 0, problems=problems, runs=run_names,
        notes=notes_list,
    )

