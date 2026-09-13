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
from harness.verify.mutation import deduplicate_mutants, hunk_revert_mutants
from harness.verify.verdict import decide



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

