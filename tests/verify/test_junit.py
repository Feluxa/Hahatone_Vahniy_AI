import tempfile
from pathlib import Path

from harness.contracts import TestOutcome
from harness.verify.junit import parse_junit, with_missing


def test_parse_junit_various_outcomes() -> None:
    xml_content = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
    <testsuite name="pytest" errors="1" failures="1" skipped="1" tests="4" time="0.123">
        <testcase classname="tests.test_settlement" name="test_refund_reduces_net" file="tests/test_settlement.py" line="10" time="0.01">
            <failure message="assert 130 == 70" type="AssertionError">def test_refund_reduces_net():\n    assert 130 == 70</failure>
        </testcase>
        <testcase classname="tests.test_settlement" name="test_broken_import" file="/app/repo/tests/test_settlement.py" line="20" time="0.02">
            <error message="No module named 'foo'" type="ModuleNotFoundError">Traceback: ...</error>
        </testcase>
        <testcase classname="tests.test_settlement" name="test_skipped" file="/tests/test_settlement.py" line="30" time="0.00">
            <skipped message="skip reason" />
        </testcase>
        <testcase classname="tests.test_settlement" name="test_success" file="tests/test_settlement.py" line="40" time="0.05" />
    </testsuite>
</testsuites>
"""
    with tempfile.NamedTemporaryFile("w", suffix=".xml", encoding="utf-8", delete=False) as f:
        f.write(xml_content)
        f_path = Path(f.name)

    try:
        reports = parse_junit(f_path)
        assert len(reports) == 4

        # 1. Failure by assert
        id_fail = "tests/test_settlement.py::test_refund_reduces_net"
        assert id_fail in reports
        assert reports[id_fail].outcome == TestOutcome.FAILED
        assert reports[id_fail].exception_type == "AssertionError"
        assert reports[id_fail].failed_by_assertion is True
        assert "assert 130 == 70" in (reports[id_fail].message or "")

        # 2. Error (Import/Environment)
        id_err = "tests/test_settlement.py::test_broken_import"
        assert id_err in reports
        assert reports[id_err].outcome == TestOutcome.ERROR
        assert reports[id_err].exception_type == "ModuleNotFoundError"
        assert reports[id_err].failed_by_assertion is False

        # 3. Skipped
        id_skip = "tests/test_settlement.py::test_skipped"
        assert id_skip in reports
        assert reports[id_skip].outcome == TestOutcome.SKIPPED

        # 4. Passed
        id_pass = "tests/test_settlement.py::test_success"
        assert id_pass in reports
        assert reports[id_pass].outcome == TestOutcome.PASSED
        assert reports[id_pass].message is None
    finally:
        f_path.unlink(missing_ok=True)


def test_parse_junit_missing_file() -> None:
    reports = parse_junit(Path("non_existent_file.xml"))
    assert reports == {}


def test_with_missing() -> None:
    xml_content = """<?xml version="1.0" encoding="utf-8"?>
<testsuite tests="1">
    <testcase classname="tests.test_one" name="test_alpha" file="tests/test_one.py" />
</testsuite>
"""
    with tempfile.NamedTemporaryFile("w", suffix=".xml", encoding="utf-8", delete=False) as f:
        f.write(xml_content)
        f_path = Path(f.name)

    try:
        reports = parse_junit(f_path)
        expected = [
            "tests/test_one.py::test_alpha",
            "tests/test_one.py::test_beta",
        ]
        augmented = with_missing(reports, expected)
        assert augmented["tests/test_one.py::test_alpha"].outcome == TestOutcome.PASSED
        assert augmented["tests/test_one.py::test_beta"].outcome == TestOutcome.MISSING
    finally:
        f_path.unlink(missing_ok=True)
