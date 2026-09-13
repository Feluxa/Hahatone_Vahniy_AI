from harness.contracts import (
    ProblemCategory,
    RepairTarget,
    RunKind,
    RunResult,
    RunScope,
    TestLists,
    TestOutcome,
    TestReport,
)
import pytest

from harness.verify.junit import parse_junit
from harness.verify.verdict import (
    EXPECTED_REWARD,
    decide,
    invalid_tests,
    reclassify_by_outcomes,
)


def _make_sample_lists() -> TestLists:
    return TestLists(
        fail_to_pass=["tests/test_x.py::test_bug"],
        pass_to_pass=["tests/test_x.py::test_existing"],
        anti_cheat=["tests/test_x.py::test_guard"],
    )


def test_decide_all_passed() -> None:
    lists = _make_sample_lists()

    base_tests = {
        "tests/test_x.py::test_bug": TestReport(outcome=TestOutcome.FAILED, exception_type="AssertionError", message="assert 1 == 2"),
        "tests/test_x.py::test_existing": TestReport(outcome=TestOutcome.PASSED),
        "tests/test_x.py::test_guard": TestReport(outcome=TestOutcome.PASSED),
    }
    oracle_tests = {
        "tests/test_x.py::test_bug": TestReport(outcome=TestOutcome.PASSED),
        "tests/test_x.py::test_existing": TestReport(outcome=TestOutcome.PASSED),
        "tests/test_x.py::test_guard": TestReport(outcome=TestOutcome.PASSED),
    }

    runs = [
        RunResult(
            name="base/full", kind=RunKind.BASE, scope=RunScope.FULL, executed=True,
            commands=["sh /tests/test.sh"], image_digest="sha256:1", duration_sec=1.0,
            exit_code=0, reward=0, report_path=None, log_dir="base/full", tests=base_tests,
        ),
        RunResult(
            name="oracle/full", kind=RunKind.ORACLE, scope=RunScope.FULL, executed=True,
            commands=["sh /solution/solve.sh && sh /tests/test.sh"], image_digest="sha256:1", duration_sec=1.0,
            exit_code=0, reward=1, report_path=None, log_dir="oracle/full", tests=oracle_tests,
        ),
        RunResult(
            name="repeat/base/full", kind=RunKind.BASE, scope=RunScope.FULL, executed=True,
            commands=["sh /tests/test.sh"], image_digest="sha256:1", duration_sec=1.0,
            exit_code=0, reward=0, report_path=None, log_dir="repeat/base/full", tests=base_tests,
            repeat_of="base/full",
        ),
        RunResult(
            name="mutant/hunk-1", kind=RunKind.MUTANT, scope=RunScope.FULL, executed=True,
            commands=["mutant"], image_digest="sha256:1", duration_sec=1.0,
            exit_code=0, reward=0, report_path=None, log_dir="mutant/hunk-1", tests=base_tests,
        ),
    ]

    verdict = decide(runs, lists, [])
    assert verdict.ok is True
    assert len(verdict.problems) == 0


def test_decide_detects_defect_not_reproduced() -> None:
    lists = _make_sample_lists()
    base_tests = {
        "tests/test_x.py::test_bug": TestReport(outcome=TestOutcome.PASSED),  # Should have failed!
        "tests/test_x.py::test_existing": TestReport(outcome=TestOutcome.PASSED),
        "tests/test_x.py::test_guard": TestReport(outcome=TestOutcome.PASSED),
    }
    runs = [
        RunResult(
            name="base/full", kind=RunKind.BASE, scope=RunScope.FULL, executed=True,
            commands=["sh /tests/test.sh"], image_digest="sha256:1", duration_sec=1.0,
            exit_code=0, reward=0, report_path=None, log_dir="base/full", tests=base_tests,
        ),
    ]
    verdict = decide(runs, lists, [])
    assert verdict.ok is False
    categories = [p.category for p in verdict.problems]
    assert ProblemCategory.BASE_F2P_PASSED in categories


def test_decide_detects_mutant_survived() -> None:
    lists = _make_sample_lists()
    runs = [
        RunResult(
            name="mutant/hunk-1", kind=RunKind.MUTANT, scope=RunScope.FULL, executed=True,
            commands=["mutant"], image_digest="sha256:1", duration_sec=1.0,
            exit_code=0, reward=1, report_path=None, log_dir="mutant/hunk-1", tests={},
        ),
    ]
    verdict = decide(runs, lists, [])
    assert verdict.ok is False
    categories = [p.category for p in verdict.problems]
    assert ProblemCategory.MUTANT_SURVIVED in categories


def _run(name: str, kind: RunKind, scope: RunScope, tests: dict, reward, **kwargs) -> RunResult:
    return RunResult(
        name=name, kind=kind, scope=scope, executed=kwargs.pop("executed", True),
        commands=["sh /tests/test.sh"], image_digest="sha256:1", duration_sec=1.0,
        exit_code=0, reward=reward, report_path=None, log_dir=name, tests=tests, **kwargs,
    )


_F2P = "tests/test_x.py::test_bug"
_P2P = "tests/test_x.py::test_existing"
_AC = "tests/test_x.py::test_guard"
_FAILED = TestReport(outcome=TestOutcome.FAILED, exception_type="AssertionError", message="assert 1 == 2")
_PASSED = TestReport(outcome=TestOutcome.PASSED)


def _full_runs() -> list[RunResult]:
    """Полные прогоны, на которых всё в порядке: проблемы должны прийти только от списков."""
    base_tests = {_F2P: _FAILED, _P2P: _PASSED, _AC: _PASSED}
    oracle_tests = {_F2P: _PASSED, _P2P: _PASSED, _AC: _PASSED}
    return [
        _run("base/full", RunKind.BASE, RunScope.FULL, base_tests, 0),
        _run("oracle/full", RunKind.ORACLE, RunScope.FULL, oracle_tests, 1),
    ]


def test_decide_detects_guard_broken_only_in_list_run() -> None:
    """p2p проходит в полном прогоне, но падает, когда список гоняется отдельно."""
    lists = _make_sample_lists()
    runs = _full_runs() + [
        _run("base/pass_to_pass", RunKind.BASE, RunScope.PASS_TO_PASS,
             {_P2P: TestReport(outcome=TestOutcome.FAILED, exception_type="AssertionError", message="boom")}, 0),
    ]

    verdict = decide(runs, lists, [])

    assert verdict.ok is False
    categories = [p.category for p in verdict.problems]
    assert ProblemCategory.BASE_GUARD_FAILED in categories
    assert any("base/pass_to_pass" in p.run_names for p in verdict.problems)


def test_decide_detects_oracle_list_run_error() -> None:
    """f2p проходит в полном прогоне oracle, но по списку падает с ошибкой импорта."""
    lists = _make_sample_lists()
    runs = _full_runs() + [
        _run("oracle/fail_to_pass", RunKind.ORACLE, RunScope.FAIL_TO_PASS,
             {_F2P: TestReport(outcome=TestOutcome.ERROR, exception_type="ImportError", message="no module")}, 0),
    ]

    verdict = decide(runs, lists, [])

    assert verdict.ok is False
    assert ProblemCategory.ORACLE_FAILED in [p.category for p in verdict.problems]


def test_decide_detects_defect_not_reproduced_in_list_run() -> None:
    lists = _make_sample_lists()
    runs = _full_runs() + [
        _run("base/fail_to_pass", RunKind.BASE, RunScope.FAIL_TO_PASS, {_F2P: _PASSED}, 0),
    ]

    verdict = decide(runs, lists, [])

    assert verdict.ok is False
    assert ProblemCategory.BASE_F2P_PASSED in [p.category for p in verdict.problems]


def test_decide_detects_wrong_reward_in_list_run() -> None:
    """После исправления test.sh прогон по списку обязан давать осмысленный reward."""
    lists = _make_sample_lists()
    runs = _full_runs() + [
        _run("oracle/anti_cheat", RunKind.ORACLE, RunScope.ANTI_CHEAT, {_AC: _PASSED}, 0),
    ]

    verdict = decide(runs, lists, [])

    assert verdict.ok is False
    problem = next(p for p in verdict.problems if p.category == ProblemCategory.REWARD_WRONG)
    assert "oracle/anti_cheat" in problem.details


def test_decide_detects_unexecuted_list_run() -> None:
    lists = _make_sample_lists()
    runs = _full_runs() + [
        _run("base/anti_cheat", RunKind.BASE, RunScope.ANTI_CHEAT, {}, None,
             executed=False, note="Timeout expired"),
    ]

    verdict = decide(runs, lists, [])

    assert verdict.ok is False
    assert ProblemCategory.TIMEOUT in [p.category for p in verdict.problems]


def test_decide_accepts_correct_list_runs() -> None:
    """Все шесть прогонов по спискам в порядке — проблем нет."""
    lists = _make_sample_lists()
    runs = _full_runs() + [
        _run("base/fail_to_pass", RunKind.BASE, RunScope.FAIL_TO_PASS, {_F2P: _FAILED}, 0),
        # pass_to_pass и anti_cheat проходят и на исходном коде, значит в своих прогонах дают 1.
        _run("base/pass_to_pass", RunKind.BASE, RunScope.PASS_TO_PASS, {_P2P: _PASSED}, 1),
        _run("base/anti_cheat", RunKind.BASE, RunScope.ANTI_CHEAT, {_AC: _PASSED}, 1),
        _run("oracle/fail_to_pass", RunKind.ORACLE, RunScope.FAIL_TO_PASS, {_F2P: _PASSED}, 1),
        _run("oracle/pass_to_pass", RunKind.ORACLE, RunScope.PASS_TO_PASS, {_P2P: _PASSED}, 1),
        _run("oracle/anti_cheat", RunKind.ORACLE, RunScope.ANTI_CHEAT, {_AC: _PASSED}, 1),
    ]

    verdict = decide(runs, lists, [])

    assert verdict.ok is True, [p.details for p in verdict.problems]


def test_decide_rejects_hunk_mutant_without_reward() -> None:
    """Патч hunk-revert не наложился: reward не записан, зачесть мутанта пойманным нельзя."""
    lists = _make_sample_lists()
    runs = _full_runs() + [
        _run("mutant/hunk-1", RunKind.MUTANT, RunScope.FULL, {}, None),
    ]

    verdict = decide(runs, lists, [])

    assert verdict.ok is False
    problem = next(p for p in verdict.problems if p.category == ProblemCategory.INTERNAL)
    assert "mutant/hunk-1" in problem.run_names


def test_decide_discards_llm_mutant_without_reward() -> None:
    """Невалидный патч от модели отбрасывается и не валит кейс (план §5.10)."""
    lists = _make_sample_lists()
    runs = _full_runs() + [
        _run("mutant/llm-mutant-off-by-one", RunKind.MUTANT, RunScope.FULL, {}, None),
    ]

    verdict = decide(runs, lists, [])

    assert verdict.ok is True, [p.details for p in verdict.problems]


def test_decide_rejects_unexecuted_hunk_mutant() -> None:
    lists = _make_sample_lists()
    runs = _full_runs() + [
        _run("mutant/hunk-2", RunKind.MUTANT, RunScope.FULL, {}, None,
             executed=False, note="Timeout expired"),
    ]

    verdict = decide(runs, lists, [])

    assert verdict.ok is False
    assert ProblemCategory.INTERNAL in [p.category for p in verdict.problems]


def test_decide_accepts_caught_mutant() -> None:
    lists = _make_sample_lists()
    runs = _full_runs() + [
        _run("mutant/hunk-1", RunKind.MUTANT, RunScope.FULL, {_F2P: _FAILED}, 0),
        _run("mutant/llm-mutant-sign-flip", RunKind.MUTANT, RunScope.FULL, {_F2P: _FAILED}, 0),
    ]

    verdict = decide(runs, lists, [])

    assert verdict.ok is True, [p.details for p in verdict.problems]


def test_decide_rejects_unexecuted_collect() -> None:
    """Упавший collect не отменяет сверку ID, а сам становится проблемой (PROTOCOL §4)."""
    lists = _make_sample_lists()
    runs = _full_runs() + [
        _run("collect", RunKind.BASE, RunScope.COLLECT, {}, None, executed=False),
    ]

    verdict = decide(runs, lists, [])

    assert verdict.ok is False
    problem = next(p for p in verdict.problems if p.category == ProblemCategory.LIST_MISMATCH)
    assert "collect" in problem.run_names
    assert problem.target == RepairTarget.TESTS


def test_decide_accepts_matching_collect() -> None:
    lists = _make_sample_lists()
    collected = {test_id: _PASSED for test_id in lists.all_ids()}
    runs = _full_runs() + [
        _run("collect", RunKind.BASE, RunScope.COLLECT, collected, None),
    ]

    verdict = decide(runs, lists, [])

    assert verdict.ok is True, [p.details for p in verdict.problems]


def test_decide_reports_failed_solution_apply() -> None:
    """Отказ прогона, из которого строятся hunk-мутанты, обязан быть виден в вердикте."""
    lists = _make_sample_lists()
    runs = _full_runs() + [
        _run("oracle/apply", RunKind.ORACLE, RunScope.FULL, {}, None,
             executed=False, note="solve.sh завершился с кодом 1: sed: can't read"),
    ]

    verdict = decide(runs, lists, [])

    assert verdict.ok is False
    problem = next(p for p in verdict.problems if "hunk-мутанты не построены" in p.details)
    assert problem.category == ProblemCategory.INTERNAL
    assert problem.target == RepairTarget.NONE
    assert "solve.sh завершился с кодом 1" in problem.details


def test_decide_marks_solution_apply_timeout() -> None:
    lists = _make_sample_lists()
    runs = _full_runs() + [
        _run("oracle/apply", RunKind.ORACLE, RunScope.FULL, {}, None,
             executed=False, note="Timeout expired after 60s"),
    ]

    verdict = decide(runs, lists, [])

    problem = next(p for p in verdict.problems if "hunk-мутанты не построены" in p.details)
    assert problem.category == ProblemCategory.TIMEOUT


def test_decide_accepts_successful_solution_apply() -> None:
    lists = _make_sample_lists()
    runs = _full_runs() + [
        _run("oracle/apply", RunKind.ORACLE, RunScope.FULL, {}, None),
    ]

    verdict = decide(runs, lists, [])

    assert verdict.ok is True, [p.details for p in verdict.problems]


@pytest.mark.parametrize(("run_name", "expected"), sorted(EXPECTED_REWARD.items()))
def test_expected_reward_table_is_enforced(run_name: str, expected: int) -> None:
    """Каждая строка таблицы ожидаемых reward проверяется вердиктом.

    test.sh пишет 1, когда все собранные тесты прошли, поэтому base/pass_to_pass и
    base/anti_cheat обязаны давать 1, а не 0: их тесты проходят и на исходном коде.
    """
    lists = _make_sample_lists()
    kind = RunKind.BASE if run_name.startswith("base/") else RunKind.ORACLE
    scope = {
        "full": RunScope.FULL,
        "fail_to_pass": RunScope.FAIL_TO_PASS,
        "pass_to_pass": RunScope.PASS_TO_PASS,
        "anti_cheat": RunScope.ANTI_CHEAT,
    }[run_name.split("/", 1)[1]]

    if run_name.startswith("base/") and "fail_to_pass" in run_name:
        tests = {_F2P: _FAILED}
    elif run_name == "base/full":
        tests = {_F2P: _FAILED, _P2P: _PASSED, _AC: _PASSED}
    elif run_name.endswith("/full"):
        tests = {_F2P: _PASSED, _P2P: _PASSED, _AC: _PASSED}
    else:
        key = {"fail_to_pass": _F2P, "pass_to_pass": _P2P, "anti_cheat": _AC}[run_name.split("/", 1)[1]]
        tests = {key: _PASSED}

    def runs_with(reward: int) -> list[RunResult]:
        base = {r.name: r for r in _full_runs()}
        base[run_name] = _run(run_name, kind, scope, tests, reward)
        return list(base.values())

    # Ожидаемый reward — проблем нет.
    good = decide(runs_with(expected), lists, [])
    assert not [p for p in good.problems if p.category == ProblemCategory.REWARD_WRONG], (
        [p.details for p in good.problems]
    )

    # Противоположный — ровно одна проблема REWARD_WRONG про этот прогон.
    bad = decide(runs_with(1 - expected), lists, [])
    wrong = [p for p in bad.problems if p.category == ProblemCategory.REWARD_WRONG]
    assert [p.run_names for p in wrong] == [[run_name]]
    assert f"expected {expected}" in wrong[0].details


def test_valid_case_with_all_eight_runs_is_ready() -> None:
    """Полная матрица с правильными reward не даёт ни одной проблемы."""
    lists = _make_sample_lists()
    tests_by_run = {
        "base/full": {_F2P: _FAILED, _P2P: _PASSED, _AC: _PASSED},
        "base/fail_to_pass": {_F2P: _FAILED},
        "base/pass_to_pass": {_P2P: _PASSED},
        "base/anti_cheat": {_AC: _PASSED},
        "oracle/full": {_F2P: _PASSED, _P2P: _PASSED, _AC: _PASSED},
        "oracle/fail_to_pass": {_F2P: _PASSED},
        "oracle/pass_to_pass": {_P2P: _PASSED},
        "oracle/anti_cheat": {_AC: _PASSED},
    }
    scopes = {
        "full": RunScope.FULL, "fail_to_pass": RunScope.FAIL_TO_PASS,
        "pass_to_pass": RunScope.PASS_TO_PASS, "anti_cheat": RunScope.ANTI_CHEAT,
    }
    runs = [
        _run(
            name,
            RunKind.BASE if name.startswith("base/") else RunKind.ORACLE,
            scopes[name.split("/", 1)[1]],
            tests,
            EXPECTED_REWARD[name],
        )
        for name, tests in tests_by_run.items()
    ]

    verdict = decide(runs, lists, [])

    assert verdict.ok is True, [p.details for p in verdict.problems]


_ASSERT_FAIL = TestReport(outcome=TestOutcome.FAILED, exception_type="AssertionError", message="assert 5 == -5")
_ERROR = TestReport(outcome=TestOutcome.ERROR, exception_type="ImportError", message="no module named psycopg")


def _full_pair(base_tests: dict, oracle_tests: dict) -> list[RunResult]:
    return [
        _run("base/full", RunKind.BASE, RunScope.FULL, base_tests, 0),
        _run("oracle/full", RunKind.ORACLE, RunScope.FULL, oracle_tests, 1),
    ]


def test_reclassify_moves_defect_catcher_from_pass_to_pass() -> None:
    """Падает на base по assert, проходит на oracle — это fail_to_pass, что бы ни сказала модель."""
    lists = TestLists(fail_to_pass=[_F2P], pass_to_pass=[_P2P], anti_cheat=[_AC])
    runs = _full_pair(
        {_F2P: _FAILED, _P2P: _ASSERT_FAIL, _AC: _PASSED},
        {_F2P: _PASSED, _P2P: _PASSED, _AC: _PASSED},
    )

    new_lists, notes = reclassify_by_outcomes(lists, runs)

    assert new_lists.fail_to_pass == [_F2P, _P2P]
    assert new_lists.pass_to_pass == []
    assert new_lists.anti_cheat == [_AC]
    assert len(notes) == 1
    assert notes[0].startswith(f"тест {_P2P} перенесён в fail_to_pass по фактическим исходам")


def test_reclassified_case_becomes_ok() -> None:
    """После переноса кейс валиден: прогоны по спискам идут уже по новой раскладке."""
    lists = TestLists(fail_to_pass=[_F2P], pass_to_pass=[_P2P], anti_cheat=[_AC])
    full = _full_pair(
        {_F2P: _FAILED, _P2P: _ASSERT_FAIL, _AC: _PASSED},
        {_F2P: _PASSED, _P2P: _PASSED, _AC: _PASSED},
    )

    new_lists, notes = reclassify_by_outcomes(lists, full)
    runs = full + [
        _run("base/fail_to_pass", RunKind.BASE, RunScope.FAIL_TO_PASS,
             {_F2P: _FAILED, _P2P: _ASSERT_FAIL}, 0),
        _run("base/anti_cheat", RunKind.BASE, RunScope.ANTI_CHEAT, {_AC: _PASSED}, 1),
        _run("oracle/fail_to_pass", RunKind.ORACLE, RunScope.FAIL_TO_PASS,
             {_F2P: _PASSED, _P2P: _PASSED}, 1),
        _run("oracle/anti_cheat", RunKind.ORACLE, RunScope.ANTI_CHEAT, {_AC: _PASSED}, 1),
    ]

    verdict = decide(runs, new_lists, [], notes=notes)

    assert verdict.ok is True, [p.details for p in verdict.problems]
    assert verdict.notes == notes


def test_reclassify_leaves_test_failing_on_oracle() -> None:
    """Падает и на oracle — это проблема для ремонта, а не ошибка классификации."""
    lists = TestLists(fail_to_pass=[_F2P], pass_to_pass=[_P2P], anti_cheat=[])
    runs = _full_pair(
        {_F2P: _FAILED, _P2P: _ASSERT_FAIL},
        {_F2P: _PASSED, _P2P: _ASSERT_FAIL},
    )

    new_lists, notes = reclassify_by_outcomes(lists, runs)

    assert new_lists.pass_to_pass == [_P2P]
    assert new_lists.fail_to_pass == [_F2P]
    assert notes == []


def test_reclassify_leaves_test_failing_on_base_by_error() -> None:
    """Ошибка импорта или окружения не заменяет проверку дефекта (PROTOCOL §5.4)."""
    lists = TestLists(fail_to_pass=[_F2P], pass_to_pass=[_P2P], anti_cheat=[])
    runs = _full_pair({_F2P: _FAILED, _P2P: _ERROR}, {_F2P: _PASSED, _P2P: _PASSED})

    new_lists, notes = reclassify_by_outcomes(lists, runs)

    assert new_lists.pass_to_pass == [_P2P]
    assert notes == []


def test_reclassify_leaves_test_passing_everywhere() -> None:
    lists = TestLists(fail_to_pass=[_F2P], pass_to_pass=[_P2P], anti_cheat=[_AC])
    runs = _full_pair(
        {_F2P: _FAILED, _P2P: _PASSED, _AC: _PASSED},
        {_F2P: _PASSED, _P2P: _PASSED, _AC: _PASSED},
    )

    new_lists, notes = reclassify_by_outcomes(lists, runs)

    assert new_lists == lists
    assert notes == []


def test_reclassify_needs_both_full_runs() -> None:
    """Без исходов гадать нельзя: неудачный прогон не повод перекладывать тесты."""
    lists = TestLists(fail_to_pass=[_F2P], pass_to_pass=[_P2P], anti_cheat=[])
    runs = [
        _run("base/full", RunKind.BASE, RunScope.FULL, {_P2P: _ASSERT_FAIL}, 0),
        _run("oracle/full", RunKind.ORACLE, RunScope.FULL, {}, None, executed=False),
    ]

    new_lists, notes = reclassify_by_outcomes(lists, runs)

    assert new_lists == lists
    assert notes == []


def test_reclassify_also_moves_from_anti_cheat() -> None:
    lists = TestLists(fail_to_pass=[_F2P], pass_to_pass=[], anti_cheat=[_AC])
    runs = _full_pair({_F2P: _FAILED, _AC: _ASSERT_FAIL}, {_F2P: _PASSED, _AC: _PASSED})

    new_lists, notes = reclassify_by_outcomes(lists, runs)

    assert new_lists.anti_cheat == []
    assert new_lists.fail_to_pass == [_F2P, _AC]
    assert len(notes) == 1


def test_failed_collect_problem_carries_the_error_text() -> None:
    """Без текста ошибки ремонт три итерации чинит вслепую."""
    lists = _make_sample_lists()
    note = (
        "pytest --collect-only завершился с кодом 2:\n"
        'E   File "/tests/test_case.py", line 2\n'
        "E   SyntaxError: 'async with' outside async function"
    )
    runs = _full_runs() + [
        _run("collect", RunKind.BASE, RunScope.COLLECT, {}, None, executed=False, note=note),
    ]

    verdict = decide(runs, lists, [])

    problem = next(p for p in verdict.problems if p.category == ProblemCategory.LIST_MISMATCH)
    assert "SyntaxError: 'async with' outside async function" in problem.details
    assert "test_case.py" in problem.details
    assert problem.target == RepairTarget.TESTS


_VALIDATION_ERROR = TestReport(
    outcome=TestOutcome.ERROR,
    exception_type="ValidationError",
    message="1 validation error for Model: kind — input should be 'purchase' or 'refund'",
)


def test_invalid_test_gets_one_problem_and_no_product_diagnosis() -> None:
    """Тест падает одинаково до и после решения: виноват тест, а не продукт."""
    lists = _make_sample_lists()
    base_tests = {_F2P: _FAILED, _P2P: _VALIDATION_ERROR, _AC: _PASSED}
    oracle_tests = {_F2P: _PASSED, _P2P: _VALIDATION_ERROR, _AC: _PASSED}
    runs = [
        _run("base/full", RunKind.BASE, RunScope.FULL, base_tests, 0),
        _run("oracle/full", RunKind.ORACLE, RunScope.FULL, oracle_tests, 0),
    ]

    verdict = decide(runs, lists, [])

    assert verdict.ok is False
    assert len(verdict.problems) == 1
    problem = verdict.problems[0]
    assert problem.category == ProblemCategory.TEST_INVALID
    assert problem.target == RepairTarget.TESTS
    assert problem.test_ids == [_P2P]
    assert "ValidationError" in problem.details
    assert "Исправь тест, не решение" in problem.details

    # Ничего из того, что увело бы ремонт в solve.sh.
    categories = {p.category for p in verdict.problems}
    assert ProblemCategory.ORACLE_FAILED not in categories
    assert ProblemCategory.BASE_GUARD_FAILED not in categories
    assert ProblemCategory.BASE_NOT_ASSERTION not in categories
    assert ProblemCategory.REWARD_WRONG not in categories
    assert not any(p.target == RepairTarget.SOLUTION for p in verdict.problems)


def test_invalid_test_in_fail_to_pass_is_not_diagnosed_as_product() -> None:
    """Тот же диагноз, если невалидный тест объявлен в fail_to_pass."""
    lists = TestLists(fail_to_pass=[_F2P], pass_to_pass=[], anti_cheat=[])
    runs = [
        _run("base/full", RunKind.BASE, RunScope.FULL, {_F2P: _VALIDATION_ERROR}, 0),
        _run("oracle/full", RunKind.ORACLE, RunScope.FULL, {_F2P: _VALIDATION_ERROR}, 0),
    ]

    verdict = decide(runs, lists, [])

    assert [p.category for p in verdict.problems] == [ProblemCategory.TEST_INVALID]


def test_defect_catcher_diagnosis_is_unchanged() -> None:
    """Падает на base по assert и проходит на oracle — обычный fail_to_pass, как раньше."""
    lists = TestLists(fail_to_pass=[_F2P], pass_to_pass=[_P2P], anti_cheat=[_AC])
    base_tests = {_F2P: _FAILED, _P2P: _PASSED, _AC: _PASSED}
    oracle_tests = {_F2P: _PASSED, _P2P: _PASSED, _AC: _PASSED}
    runs = [
        _run("base/full", RunKind.BASE, RunScope.FULL, base_tests, 0),
        _run("oracle/full", RunKind.ORACLE, RunScope.FULL, oracle_tests, 1),
    ]

    verdict = decide(runs, lists, [])

    assert verdict.ok is True, [p.details for p in verdict.problems]
    assert invalid_tests(runs) == {}


def test_different_exception_on_base_and_oracle_is_not_invalid() -> None:
    """Разные исключения — продукт всё-таки влияет, это не «тест сам по себе сломан»."""
    runs = [
        _run("base/full", RunKind.BASE, RunScope.FULL,
             {_P2P: TestReport(outcome=TestOutcome.ERROR, exception_type="KeyError", message="k")}, 0),
        _run("oracle/full", RunKind.ORACLE, RunScope.FULL,
             {_P2P: TestReport(outcome=TestOutcome.ERROR, exception_type="TypeError", message="t")}, 1),
    ]

    assert invalid_tests(runs) == {}


def test_same_assertion_on_base_and_oracle_is_not_invalid() -> None:
    """AssertionError на обоих — это провал продукта или теста по существу, не наш случай."""
    runs = [
        _run("base/full", RunKind.BASE, RunScope.FULL, {_P2P: _FAILED}, 0),
        _run("oracle/full", RunKind.ORACLE, RunScope.FULL, {_P2P: _FAILED}, 1),
    ]

    assert invalid_tests(runs) == {}


def test_invalid_test_detected_across_list_runs() -> None:
    """Диагноз ставится и по прогонам списков, не только по полным."""
    runs = [
        _run("base/anti_cheat", RunKind.BASE, RunScope.ANTI_CHEAT, {_AC: _VALIDATION_ERROR}, 0),
        _run("oracle/anti_cheat", RunKind.ORACLE, RunScope.ANTI_CHEAT, {_AC: _VALIDATION_ERROR}, 0),
    ]

    assert set(invalid_tests(runs)) == {_AC}


# Настоящая форма отчёта pytest: атрибута type нет, имя исключения — в последней
# строке трейсбека. Раньше такой отчёт молча становился AssertionError.
_DB_FAILURE_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="0" failures="1" skipped="0" tests="1" time="0.1">
<testcase classname="tests.test_x" name="test_bug" file="tests/test_x.py" time="0.0">
<failure message="psycopg.errors.UndefinedTable: relation &quot;daily_settlement&quot; does not exist">\
E       psycopg.errors.UndefinedTable: relation "daily_settlement" does not exist

/tests/test_x.py:12: UndefinedTable</failure></testcase>
</testsuite></testsuites>
"""


def test_database_error_is_not_a_reproduced_defect(tmp_path) -> None:
    """Дефект должен воспроизводиться assert'ом, а не сбоем БД (PROTOCOL §5.4).

    Отчёт берётся из разбора настоящего XML, а не собирается руками: именно на разборе
    и ломалась проверка — неопознанное исключение по умолчанию объявлялось AssertionError.
    """
    xml_path = tmp_path / "tests.xml"
    xml_path.write_text(_DB_FAILURE_XML, encoding="utf-8")
    base_f2p = parse_junit(xml_path)[_F2P]
    assert base_f2p.exception_type == "UndefinedTable"

    lists = _make_sample_lists()
    runs = [
        _run("base/full", RunKind.BASE, RunScope.FULL,
             {_F2P: base_f2p, _P2P: _PASSED, _AC: _PASSED}, 0),
        _run("oracle/full", RunKind.ORACLE, RunScope.FULL,
             {_F2P: _PASSED, _P2P: _PASSED, _AC: _PASSED}, 1),
    ]

    verdict = decide(runs, lists, [])

    assert verdict.ok is False
    not_assertion = [
        p for p in verdict.problems if p.category == ProblemCategory.BASE_NOT_ASSERTION
    ]
    assert len(not_assertion) == 1
    assert not_assertion[0].test_ids == [_F2P]
    assert "UndefinedTable" in not_assertion[0].details
