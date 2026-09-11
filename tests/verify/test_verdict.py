from harness.contracts import (
    ProblemCategory,
    RunKind,
    RunResult,
    RunScope,
    TestLists,
    TestOutcome,
    TestReport,
)
from harness.verify.verdict import decide


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
