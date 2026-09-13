"""Альтернативное корректное решение: тесты обязаны его принять (PROTOCOL §5.7)."""
from pathlib import Path

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
from harness.verify.junit import parse_junit, with_missing
from harness.verify.verdict import decide

F2P = "tests/test_x.py::test_f2p"
P2P = "tests/test_x.py::test_p2p"
AC = "tests/test_x.py::test_ac"

# Настоящий вывод pytest при сломанном сборе: у <error> нет атрибута type, а ожидаемые
# тесты вообще не попадают в отчёт. Собранный руками TestReport эту ветку не проверяет.
COLLECTION_FAILURE_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="1" failures="0" skipped="0" tests="1" time="0.1">
<testcase classname="" name="tests.test_x" time="0.000"><error message="collection failure">\
tests/test_x.py:1: in &lt;module&gt;
    import settlement
E   SyntaxError: invalid syntax</error></testcase></testsuite></testsuites>
"""


def _lists() -> TestLists:
    return TestLists(fail_to_pass=[F2P], pass_to_pass=[P2P], anti_cheat=[AC])


def _run(
    name: str, kind: RunKind, reward: int | None, tests: dict[str, TestReport], *,
    executed: bool = True,
) -> RunResult:
    return RunResult(
        name=name, kind=kind, scope=RunScope.FULL, executed=executed,
        commands=["sh", "/tests/test.sh"], image_digest="sha256:test", duration_sec=1.0,
        exit_code=0 if reward else 1, reward=reward,
        report_path=f"{name}/verifier/tests.xml", log_dir=name, tests=tests,
    )


def _base_and_oracle() -> list[RunResult]:
    """Пара base/oracle без замечаний: вердикт упирается только в проверяемый прогон."""
    return [
        _run("base/full", RunKind.BASE, 0, {
            F2P: TestReport(outcome=TestOutcome.FAILED, exception_type="AssertionError"),
        }),
        _run("oracle/full", RunKind.ORACLE, 1, {F2P: TestReport(outcome=TestOutcome.PASSED)}),
    ]


def _passing_mutant() -> RunResult:
    """Обычный мутант, честно пойманный тестами: чтобы ноты о мутантах не мешали."""
    return _run("mutant/llm-mutant-sign", RunKind.MUTANT, 0, {
        F2P: TestReport(outcome=TestOutcome.FAILED, exception_type="AssertionError"),
        P2P: TestReport(outcome=TestOutcome.PASSED),
        AC: TestReport(outcome=TestOutcome.PASSED),
    })


def _alt_run(reward: int | None, tests: dict[str, TestReport], *, executed: bool = True) -> RunResult:
    return _run(
        "mutant/alt-solution-reordered", RunKind.MUTANT, reward, tests, executed=executed,
    )


def test_accepted_alternative_leaves_verdict_clean() -> None:
    alt = _alt_run(1, {
        F2P: TestReport(outcome=TestOutcome.PASSED),
        P2P: TestReport(outcome=TestOutcome.PASSED),
        AC: TestReport(outcome=TestOutcome.PASSED),
    })

    verdict = decide([*_base_and_oracle(), _passing_mutant(), alt], _lists(), [])

    assert not any(
        p.category == ProblemCategory.ALTERNATIVE_SOLUTION_FAILED for p in verdict.problems
    )
    assert not any("альтернативное корректное решение" in note.lower() for note in verdict.notes)


def test_rejected_alternative_blames_tests() -> None:
    """Тесты, отвергшие эквивалентную реализацию, переобучены на дифф эталона."""
    alt = _alt_run(0, {
        F2P: TestReport(outcome=TestOutcome.FAILED, exception_type="AssertionError"),
        P2P: TestReport(outcome=TestOutcome.PASSED),
        AC: TestReport(outcome=TestOutcome.PASSED),
    })

    verdict = decide([*_base_and_oracle(), _passing_mutant(), alt], _lists(), [])

    assert verdict.ok is False
    failures = [
        p for p in verdict.problems
        if p.category == ProblemCategory.ALTERNATIVE_SOLUTION_FAILED
    ]
    assert len(failures) == 1
    problem = failures[0]
    # Чинить надо тест, а не решение: решение здесь по условию корректно.
    assert problem.target == RepairTarget.TESTS
    assert problem.test_ids == [F2P]
    assert problem.run_names == ["mutant/alt-solution-reordered"]


def test_alternative_that_broke_the_build_is_not_blamed_on_tests(tmp_path: Path) -> None:
    """Сломался сам вариант — тесты ни при чём, но и проверки не было: это проблема."""
    xml_path = tmp_path / "alt.xml"
    xml_path.write_text(COLLECTION_FAILURE_XML, encoding="utf-8")
    alt = _alt_run(0, with_missing(parse_junit(xml_path), [F2P, P2P, AC]))

    verdict = decide([*_base_and_oracle(), _passing_mutant(), alt], _lists(), [])

    # Тесты не виноваты: их никто не отверг.
    assert not any(
        p.category == ProblemCategory.ALTERNATIVE_SOLUTION_FAILED for p in verdict.problems
    )
    # Но запланированная проверка не выполнена, и это не INFO в лог, а проблема.
    internal = [p for p in verdict.problems if p.category == ProblemCategory.INTERNAL]
    assert len(internal) == 1
    assert internal[0].target == RepairTarget.NONE
    assert "не проверено" in internal[0].details
    assert any("альтернативное корректное решение не проводилась" in n.lower()
               for n in verdict.notes)


def test_alternative_that_did_not_apply_is_a_problem() -> None:
    """Патч не наложился: тесты не виноваты, но проверка не состоялась — это проблема.

    Молчаливый INFO в лог означал бы «всё выполнившееся прошло»; пустой limitations
    обязан означать «всё запланированное выполнено».
    """
    alt = _alt_run(None, {}, executed=False)
    alt = RunResult(
        name=alt.name, kind=alt.kind, scope=alt.scope, executed=False,
        commands=alt.commands, image_digest=alt.image_digest, duration_sec=alt.duration_sec,
        exit_code=1, reward=None, report_path=alt.report_path, log_dir=alt.log_dir,
        tests={}, note="контейнер завершился с кодом 1: anchor occurs 0 times",
    )

    verdict = decide([*_base_and_oracle(), _passing_mutant(), alt], _lists(), [])

    assert not any(
        p.category == ProblemCategory.ALTERNATIVE_SOLUTION_FAILED for p in verdict.problems
    )
    internal = [p for p in verdict.problems if p.category == ProblemCategory.INTERNAL]
    assert len(internal) == 1
    assert internal[0].target == RepairTarget.NONE
    assert "anchor occurs 0 times" in internal[0].details
    assert internal[0].run_names == ["mutant/alt-solution-reordered"]
    assert any("альтернативное корректное решение не проводилась" in n.lower()
               for n in verdict.notes)


def test_missing_alternative_is_declared_in_notes() -> None:
    """Мутанты есть, альтернативы нет — односторонняя проверка, и это видно в limitations."""
    verdict = decide([*_base_and_oracle(), _passing_mutant()], _lists(), [])

    assert any("альтернативное корректное решение не проводилась" in n.lower()
               for n in verdict.notes)


def test_alternative_does_not_count_as_independent_mutant() -> None:
    """Принятая альтернатива не заменяет мутанта: она проверяет другую сторону."""
    alt = _alt_run(1, {
        F2P: TestReport(outcome=TestOutcome.PASSED),
        P2P: TestReport(outcome=TestOutcome.PASSED),
        AC: TestReport(outcome=TestOutcome.PASSED),
    })
    hunk = _run("mutant/hunk-1", RunKind.MUTANT, 0, {
        F2P: TestReport(outcome=TestOutcome.FAILED, exception_type="AssertionError"),
    })

    verdict = decide([*_base_and_oracle(), hunk, alt], _lists(), [])

    assert any("только на основе hunk-revert" in note for note in verdict.notes)


def test_surviving_alternative_is_not_reported_as_surviving_mutant() -> None:
    """reward 1 у альтернативы — это успех, а не уцелевший мутант."""
    alt = _alt_run(1, {F2P: TestReport(outcome=TestOutcome.PASSED)})

    verdict = decide([*_base_and_oracle(), _passing_mutant(), alt], _lists(), [])

    assert not any(
        p.category == ProblemCategory.MUTANT_SURVIVED for p in verdict.problems
    )
