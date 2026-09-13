from pathlib import Path

from harness.contracts import (
    Mutant,
    MutantSource,
    RunKind,
    RunResult,
    RunScope,
    TestLists,
    TestOutcome,
    TestReport,
)
from harness.verify.junit import parse_junit, with_missing
from harness.verify.mutation import deduplicate_mutants, hunk_revert_mutants
from harness.verify.verdict import _is_syntax_or_import_breaker, decide


def _lists() -> TestLists:
    return TestLists(
        fail_to_pass=["tests/test_x.py::test_f2p"],
        pass_to_pass=["tests/test_x.py::test_p2p"],
        anti_cheat=["tests/test_x.py::test_ac"],
    )


def _full_runs_ok() -> list[RunResult]:
    """Пара base/oracle без замечаний: нужна, чтобы вердикт упирался только в мутанта."""
    return [
        RunResult(
            name="base/full", kind=RunKind.BASE, scope=RunScope.FULL, executed=True,
            commands=["sh", "/tests/test.sh"], image_digest="sha256:test", duration_sec=1.0,
            exit_code=0, reward=0, report_path="base/full/verifier/tests.xml", log_dir="base/full",
            tests={
                "tests/test_x.py::test_f2p": TestReport(
                    outcome=TestOutcome.FAILED, exception_type="AssertionError",
                ),
            },
        ),
        RunResult(
            name="oracle/full", kind=RunKind.ORACLE, scope=RunScope.FULL, executed=True,
            commands=["sh", "/tests/test.sh"], image_digest="sha256:test", duration_sec=1.0,
            exit_code=0, reward=1, report_path="oracle/full/verifier/tests.xml", log_dir="oracle/full",
            tests={"tests/test_x.py::test_f2p": TestReport(outcome=TestOutcome.PASSED)},
        ),
    ]



def test_hunk_revert_fills_anchor_and_replacement() -> None:
    diff_text = """--- a/sql/refresh.sql
+++ b/sql/refresh.sql
@@ -42,3 +42,3 @@
-occurred_at <= v_end
+occurred_at < v_end
"""
    mutants = hunk_revert_mutants(diff_text)
    assert len(mutants) == 1
    m = mutants[0]
    assert m.name == "hunk-1"
    assert m.file_path == "sql/refresh.sql"
    assert "occurred_at < v_end" in m.anchor
    assert "occurred_at <= v_end" in m.replacement


def test_deduplicate_mutants_drops_hunk_revert_duplicate() -> None:
    diff_text = """--- a/sql/refresh.sql
+++ b/sql/refresh.sql
@@ -42,3 +42,3 @@
-occurred_at <= v_end
+occurred_at < v_end
"""
    hunks = hunk_revert_mutants(diff_text)

    # Мутант от LLM в точности повторяет откат решения (hunk-1)
    dup_llm = Mutant(
        name="llm-mutant-boundary-inclusive",
        source=MutantSource.LLM,
        description="Duplicates hunk-revert",
        patch="",
        file_path="sql/refresh.sql",
        anchor="occurred_at < v_end",
        replacement="occurred_at <= v_end",
    )

    # Независимый мутант от LLM
    independent_llm = Mutant(
        name="llm-mutant-greater-than",
        source=MutantSource.LLM,
        description="Independent logic mutation",
        patch="",
        file_path="sql/refresh.sql",
        anchor="occurred_at < v_end",
        replacement="occurred_at > v_end",
    )

    result_mutants, dropped = deduplicate_mutants(hunks, [dup_llm, independent_llm])

    # Должен остаться hunk и независимый мутант, дубликат отброшен
    assert len(result_mutants) == 2
    names = [m.name for m in result_mutants]
    assert "hunk-1" in names
    assert "llm-mutant-greater-than" in names
    assert "llm-mutant-boundary-inclusive" not in names

    assert len(dropped) == 1
    assert "llm-mutant-boundary-inclusive" in dropped[0]
    assert "hunk-revert" in dropped[0]


def test_deduplicate_mutants_drops_duplicate_llm_mutants() -> None:
    hunks: list[Mutant] = []
    m1 = Mutant(
        name="llm-mutant-1",
        source=MutantSource.LLM,
        description="First",
        patch="",
        file_path="pkg/calc.py",
        anchor="a + b",
        replacement="a - b",
    )
    m2 = Mutant(
        name="llm-mutant-2",
        source=MutantSource.LLM,
        description="Second identical",
        patch="",
        file_path="pkg/calc.py",
        anchor="  a + b  \n",
        replacement="  a - b  \n",
    )

    result, dropped = deduplicate_mutants(hunks, [m1, m2])
    assert len(result) == 1
    assert result[0].name == "llm-mutant-1"
    assert len(dropped) == 1
    assert "llm-mutant-2" in dropped[0]


def test_verdict_rejects_mutant_breaking_syntax() -> None:
    lists = TestLists(
        fail_to_pass=["tests/test_x.py::test_f2p"],
        pass_to_pass=["tests/test_x.py::test_p2p"],
        anti_cheat=["tests/test_x.py::test_ac"],
    )

    # Базовые и оракул прогоны успешны
    full_runs = [
        RunResult(
            name="base/full",
            kind=RunKind.BASE,
            scope=RunScope.FULL,
            executed=True,
            commands=["sh", "/tests/test.sh"],
            image_digest="sha256:test",
            duration_sec=1.0,
            exit_code=0,
            reward=0,
            report_path="base/full/verifier/tests.xml",
            log_dir="base/full",
            tests={"tests/test_x.py::test_f2p": TestReport(outcome=TestOutcome.FAILED, exception_type="AssertionError")},
        ),
        RunResult(
            name="oracle/full",
            kind=RunKind.ORACLE,
            scope=RunScope.FULL,
            executed=True,
            commands=["sh", "/tests/test.sh"],
            image_digest="sha256:test",
            duration_sec=1.0,
            exit_code=0,
            reward=1,
            report_path="oracle/full/verifier/tests.xml",
            log_dir="oracle/full",
            tests={"tests/test_x.py::test_f2p": TestReport(outcome=TestOutcome.PASSED)},
        ),
    ]

    # Мутант, который дал reward=0 только из-за SyntaxError (все тесты сломались при импорте)
    syntax_broken_mutant_run = RunResult(
        name="mutant/llm-mutant-bad-syntax",
        kind=RunKind.MUTANT,
        scope=RunScope.FULL,
        executed=True,
        commands=["sh", "/tests/test.sh"],
        image_digest="sha256:test",
        duration_sec=1.0,
        exit_code=2,
        reward=0,
        report_path="mutant/llm-mutant-bad-syntax/verifier/tests.xml",
        log_dir="mutant/llm-mutant-bad-syntax",
        tests={
            "tests/test_x.py::test_f2p": TestReport(outcome=TestOutcome.ERROR, exception_type="SyntaxError"),
        },
    )

    verdict = decide(full_runs + [syntax_broken_mutant_run], lists, [])

    # Мутант с синтаксической ошибкой отброшен, но поскольку независимых не осталось, есть note
    assert any("Мутант mutant/llm-mutant-bad-syntax отброшен: вызвал сбой импорта/синтаксиса" in n for n in verdict.notes)
    assert any("Мутационное тестирование проведено только на основе hunk-revert" in n for n in verdict.notes)


def test_verdict_notes_when_no_independent_mutants() -> None:
    lists = TestLists(
        fail_to_pass=["tests/test_x.py::test_f2p"],
        pass_to_pass=["tests/test_x.py::test_p2p"],
        anti_cheat=["tests/test_x.py::test_ac"],
    )

    base_tests = {
        "tests/test_x.py::test_f2p": TestReport(outcome=TestOutcome.FAILED, exception_type="AssertionError"),
        "tests/test_x.py::test_p2p": TestReport(outcome=TestOutcome.PASSED),
        "tests/test_x.py::test_ac": TestReport(outcome=TestOutcome.PASSED),
    }
    oracle_tests = {
        "tests/test_x.py::test_f2p": TestReport(outcome=TestOutcome.PASSED),
        "tests/test_x.py::test_p2p": TestReport(outcome=TestOutcome.PASSED),
        "tests/test_x.py::test_ac": TestReport(outcome=TestOutcome.PASSED),
    }

    full_runs = [
        RunResult(
            name="base/full",
            kind=RunKind.BASE,
            scope=RunScope.FULL,
            executed=True,
            commands=["sh", "/tests/test.sh"],
            image_digest="sha256:test",
            duration_sec=1.0,
            exit_code=0,
            reward=0,
            report_path=None,
            log_dir="base/full",
            tests=base_tests,
        ),
        RunResult(
            name="oracle/full",
            kind=RunKind.ORACLE,
            scope=RunScope.FULL,
            executed=True,
            commands=["sh", "/tests/test.sh"],
            image_digest="sha256:test",
            duration_sec=1.0,
            exit_code=0,
            reward=1,
            report_path=None,
            log_dir="oracle/full",
            tests=oracle_tests,
        ),
    ]

    # Только hunk-revert мутант
    hunk_run = RunResult(
        name="mutant/hunk-1",
        kind=RunKind.MUTANT,
        scope=RunScope.FULL,
        executed=True,
        commands=["sh", "/tests/test.sh"],
        image_digest="sha256:test",
        duration_sec=1.0,
        exit_code=0,
        reward=0,
        report_path=None,
        log_dir="mutant/hunk-1",
        tests=base_tests,
    )

    verdict = decide(full_runs + [hunk_run], lists, [])
    assert verdict.ok is True, [p.details for p in verdict.problems]
    assert any("Мутационное тестирование проведено только на основе hunk-revert" in n for n in verdict.notes)



# Настоящий вывод pytest 8.x при SyntaxError в модуле репозитория, который импортирует тест.
# Важны ровно две детали, на которых ломалась прежняя проверка: у <error> нет атрибута type
# (pytest пишет его только у <skipped>), а имя исключения стоит последней строкой трейсбека.
COLLECTION_FAILURE_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="1" failures="0" skipped="0" tests="1" time="0.135">
<testcase classname="" name="tests.test_case" time="0.000"><error message="collection failure">\
/usr/lib/python3.11/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests/test_case.py:1: in &lt;module&gt;
    import settlement
E     File "/app/repo/settlement.py", line 12
E       def compute(:
E                   ^
E   SyntaxError: invalid syntax</error></testcase></testsuite></testsuites>
"""


def _mutant_run_from_xml(tmp_path: Path, name: str, xml: str, expected_ids: list[str]) -> RunResult:
    """Прогон мутанта, собранный из настоящего отчёта pytest, а не из TestReport руками."""
    xml_path = tmp_path / f"{name}.xml"
    xml_path.write_text(xml, encoding="utf-8")
    return RunResult(
        name=f"mutant/{name}",
        kind=RunKind.MUTANT,
        scope=RunScope.FULL,
        executed=True,
        commands=["sh", "/tests/test.sh"],
        image_digest="sha256:test",
        duration_sec=1.0,
        exit_code=2,
        reward=0,
        report_path=str(xml_path),
        log_dir=f"mutant/{name}",
        tests=with_missing(parse_junit(xml_path), expected_ids),
    )


def test_collection_failure_is_rejected_as_breaker(tmp_path: Path) -> None:
    """Мутант, сломавший сбор тестов, не засчитывается пойманным.

    Проверка идёт через настоящий отчёт pytest: у <error> нет атрибута type, поэтому
    отчёт, собранный руками с exception_type='SyntaxError', эту ветку не покрывает.
    """
    expected_ids = ["tests/test_x.py::test_f2p", "tests/test_x.py::test_p2p", "tests/test_x.py::test_ac"]
    run = _mutant_run_from_xml(tmp_path, "llm-mutant-bad-syntax", COLLECTION_FAILURE_XML, expected_ids)

    # Ни одного вердикта по тестам: всё либо ошибка сбора, либо ненайденный тест.
    assert all(
        rep.outcome in (TestOutcome.ERROR, TestOutcome.MISSING) for rep in run.tests.values()
    )
    assert _is_syntax_or_import_breaker(run) is True

    verdict = decide(_full_runs_ok() + [run], _lists(), [])
    assert any("отброшен: вызвал сбой импорта/синтаксиса" in note for note in verdict.notes)
    assert any("только на основе hunk-revert" in note for note in verdict.notes)


def test_mutant_caught_by_assertion_counts_as_independent(tmp_path: Path) -> None:
    """Мутант, пойманный настоящим assert, остаётся независимым свидетельством."""
    xml = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="0" failures="1" skipped="0" tests="3" time="0.2">
<testcase classname="tests.test_x" name="test_f2p" file="tests/test_x.py" time="0.01">
<failure message="assert Decimal('70') == Decimal('130')">assert 70 == 130</failure></testcase>
<testcase classname="tests.test_x" name="test_p2p" file="tests/test_x.py" time="0.01" />
<testcase classname="tests.test_x" name="test_ac" file="tests/test_x.py" time="0.01" />
</testsuite></testsuites>
"""
    expected_ids = ["tests/test_x.py::test_f2p", "tests/test_x.py::test_p2p", "tests/test_x.py::test_ac"]
    run = _mutant_run_from_xml(tmp_path, "llm-mutant-sign", xml, expected_ids)

    assert _is_syntax_or_import_breaker(run) is False

    verdict = decide(_full_runs_ok() + [run], _lists(), [])
    assert not any("отброшен" in note for note in verdict.notes)
    assert not any("только на основе hunk-revert" in note for note in verdict.notes)


def test_import_error_is_rejected_even_when_other_tests_ran(tmp_path: Path) -> None:
    """Часть тестов отработала, но модуль репозитория не импортировался — мутант не в счёт."""
    xml = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="1" failures="0" skipped="0" tests="2" time="0.2">
<testcase classname="tests.test_x" name="test_f2p" file="tests/test_x.py" time="0.01">
<error message="collection failure">E   ModuleNotFoundError: No module named 'settlement'</error></testcase>
<testcase classname="tests.test_x" name="test_p2p" file="tests/test_x.py" time="0.01" />
</testsuite></testsuites>
"""
    expected_ids = ["tests/test_x.py::test_f2p", "tests/test_x.py::test_p2p", "tests/test_x.py::test_ac"]
    run = _mutant_run_from_xml(tmp_path, "llm-mutant-drop-import", xml, expected_ids)

    assert run.tests["tests/test_x.py::test_f2p"].exception_type == "ModuleNotFoundError"
    assert _is_syntax_or_import_breaker(run) is True


def test_alternative_solution_survives_hunk_revert_dedup() -> None:
    """Альтернативу нельзя отбрасывать по совпадению с откатом: у неё обратное ожидание."""
    diff_text = """--- a/pkg/calc.py
+++ b/pkg/calc.py
@@ -1,2 +1,2 @@
-net = purchases + refunds
+net = purchases - refunds
"""
    hunks = hunk_revert_mutants(diff_text)
    alternative = Mutant(
        name="alt-solution-reordered",
        source=MutantSource.ALTERNATIVE_SOLUTION,
        description="Тот же расчёт другим порядком операций",
        patch="",
        file_path="pkg/calc.py",
        anchor="net = purchases - refunds",
        replacement="net = -(refunds - purchases)",
        expected_reward=1,
    )

    kept, dropped = deduplicate_mutants(hunks, [alternative])

    assert [m.name for m in kept] == ["hunk-1", "alt-solution-reordered"]
    assert dropped == []


def test_alternative_identical_to_reference_is_dropped() -> None:
    """Вариант, не отличающийся от эталона, не доказывает ничего."""
    alternative = Mutant(
        name="alt-solution-noop",
        source=MutantSource.ALTERNATIVE_SOLUTION,
        description="Ничего не изменено",
        patch="",
        file_path="pkg/calc.py",
        anchor="net = purchases - refunds",
        replacement="   net = purchases - refunds   ",
        expected_reward=1,
    )

    kept, dropped = deduplicate_mutants([], [alternative])

    assert kept == []
    assert len(dropped) == 1
