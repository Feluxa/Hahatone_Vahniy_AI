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


def _parse(xml_body: str, tmp_path: Path) -> dict:
    xml_path = tmp_path / "tests.xml"
    xml_path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<testsuites><testsuite name="pytest">'
        + xml_body
        + "</testsuite></testsuites>",
        encoding="utf-8",
    )
    return parse_junit(xml_path)


def test_failure_without_type_attribute_is_classified_by_message(tmp_path: Path) -> None:
    """pytest не пишет атрибут type у <failure>: тип берётся из первой строки сообщения.

    Раньше сюда безусловно подставлялся AssertionError, и fail_to_pass, упавший на
    TypeError, засчитывался как воспроизведённый дефект (PROTOCOL §5.4).
    """
    reports = _parse(
        '<testcase classname="tests.test_x" name="test_assert" file="tests/test_x.py">'
        '<failure message="assert 1 == 2">body</failure></testcase>'
        '<testcase classname="tests.test_x" name="test_type_error" file="tests/test_x.py">'
        '<failure message="TypeError: unsupported operand type(s) for +: &apos;NoneType&apos; and &apos;int&apos;">'
        "body</failure></testcase>",
        tmp_path,
    )

    plain = reports["tests/test_x.py::test_assert"]
    assert plain.outcome == TestOutcome.FAILED
    assert plain.exception_type == "AssertionError"
    assert plain.failed_by_assertion is True

    typed = reports["tests/test_x.py::test_type_error"]
    assert typed.outcome == TestOutcome.FAILED
    assert typed.exception_type == "TypeError"
    assert typed.failed_by_assertion is False


def test_failure_message_with_colon_is_not_mistaken_for_exception(tmp_path: Path) -> None:
    """Обычный assert с двоеточием в сообщении остаётся assert-падением."""
    reports = _parse(
        '<testcase classname="tests.test_x" name="test_dict" file="tests/test_x.py">'
        "<failure message=\"assert {'net': 130} == {'net': 70}\">body</failure></testcase>",
        tmp_path,
    )

    report = reports["tests/test_x.py::test_dict"]
    assert report.exception_type == "AssertionError"
    assert report.failed_by_assertion is True


def test_explicit_type_attribute_wins(tmp_path: Path) -> None:
    reports = _parse(
        '<testcase classname="tests.test_x" name="test_x" file="tests/test_x.py">'
        '<failure message="assert 1 == 2" type="ValueError">body</failure></testcase>',
        tmp_path,
    )

    assert reports["tests/test_x.py::test_x"].exception_type == "ValueError"


def test_error_type_is_recovered_from_traceback() -> None:
    """У <error> pytest не пишет атрибут type — имя исключения есть только в трейсбеке.

    Без этого мутант или тест, упавший на сборе, приходил с exception_type=None и
    выглядел как обычная ошибка прогона.
    """
    xml_content = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="1" failures="0" skipped="0" tests="1" time="0.1">
<testcase classname="" name="tests.test_case" time="0.000"><error message="collection failure">\
tests/test_case.py:1: in &lt;module&gt;
    import settlement
E     File "/app/repo/settlement.py", line 12
E       def compute(:
E   SyntaxError: invalid syntax</error></testcase></testsuite></testsuites>
"""
    with tempfile.NamedTemporaryFile("w", suffix=".xml", encoding="utf-8", delete=False) as f:
        f.write(xml_content)
        f_path = Path(f.name)

    try:
        reports = parse_junit(f_path)
        assert len(reports) == 1
        report = next(iter(reports.values()))
        assert report.outcome == TestOutcome.ERROR
        assert report.exception_type == "SyntaxError"
        # Провалом проверки ошибка сбора не становится ни при каких условиях.
        assert report.failed_by_assertion is False
    finally:
        f_path.unlink()


def test_error_without_exception_name_keeps_none() -> None:
    """Умолчания 'AssertionError' у <error> нет: сбой сбора не выдаётся за провал assert."""
    xml_content = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="1" failures="0" skipped="0" tests="1" time="0.1">
<testcase classname="tests.test_x" name="test_one" file="tests/test_x.py" time="0.0">
<error message="collection failure">worker 'gw0' crashed while running test</error></testcase>
</testsuite></testsuites>
"""
    with tempfile.NamedTemporaryFile("w", suffix=".xml", encoding="utf-8", delete=False) as f:
        f.write(xml_content)
        f_path = Path(f.name)

    try:
        reports = parse_junit(f_path)
        report = reports["tests/test_x.py::test_one"]
        assert report.outcome == TestOutcome.ERROR
        assert report.exception_type is None
    finally:
        f_path.unlink()


# Форма взята из настоящего отчёта pytest 8.x: атрибута type нет ни у одного <failure>,
# а имя исключения стоит последней строкой трейсбека как '<файл>:<строка>: <Имя>'.
# У голого assert это единственное место, где имя вообще есть.
FAILURE_KINDS_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="0" failures="5" skipped="0" tests="5" time="0.2">
<testcase classname="tests.test_kinds" name="test_bare_assert" file="tests/test_kinds.py" time="0.0">
<failure message="assert 130 == 70">def test_bare_assert():
&gt;       assert 130 == 70
E       assert 130 == 70

/tests/test_kinds.py:9: AssertionError</failure></testcase>
<testcase classname="tests.test_kinds" name="test_type_error" file="tests/test_kinds.py" time="0.0">
<failure message="TypeError: unsupported operand type(s)">&gt;       raise TypeError("unsupported operand type(s)")
E       TypeError: unsupported operand type(s)

/tests/test_kinds.py:17: TypeError</failure></testcase>
<testcase classname="tests.test_kinds" name="test_check_violation" file="tests/test_kinds.py" time="0.0">
<failure message="psycopg.errors.CheckViolation: violates check constraint">\
E       psycopg.errors.CheckViolation: violates check constraint

/tests/test_kinds.py:21: CheckViolation</failure></testcase>
<testcase classname="tests.test_kinds" name="test_pytest_fail" file="tests/test_kinds.py" time="0.0">
<failure message="Failed: ожидали строку">E       Failed: ожидали строку

/tests/test_kinds.py:25: Failed</failure></testcase>
<testcase classname="tests.test_kinds" name="test_no_traceback" file="tests/test_kinds.py" time="0.0">
<failure message="psycopg.errors.UndefinedTable: relation does not exist" /></testcase>
</testsuite></testsuites>
"""


def test_exception_type_is_taken_from_the_crash_line() -> None:
    """Тип исключения берётся из отчёта, а не угадывается, и умолчания AssertionError нет.

    Прежнее правило «всё непонятное — это AssertionError» засчитывало падение по любой
    неопознанной причине как воспроизведённый дефект (PROTOCOL §5.4 это запрещает).
    """
    with tempfile.NamedTemporaryFile("w", suffix=".xml", encoding="utf-8", delete=False) as f:
        f.write(FAILURE_KINDS_XML)
        f_path = Path(f.name)

    try:
        reports = parse_junit(f_path)
        by_name = {test_id.split("::")[-1]: report for test_id, report in reports.items()}

        # Голый assert: имя исключения есть только в строке места падения.
        assert by_name["test_bare_assert"].exception_type == "AssertionError"
        assert by_name["test_bare_assert"].failed_by_assertion is True

        assert by_name["test_type_error"].exception_type == "TypeError"
        assert by_name["test_type_error"].failed_by_assertion is False

        # Доменное исключение, имя которого не оканчивается на Error/Exception.
        assert by_name["test_check_violation"].exception_type == "CheckViolation"
        assert by_name["test_check_violation"].failed_by_assertion is False

        # pytest.fail — намеренный провал, а не проверка утверждения.
        assert by_name["test_pytest_fail"].exception_type == "Failed"
        assert by_name["test_pytest_fail"].failed_by_assertion is False

        # Трейсбека нет, а имя в message не опознаётся как исключение: остаётся None,
        # и такой провал не выдаётся за воспроизведённый дефект.
        assert by_name["test_no_traceback"].exception_type is None
        assert by_name["test_no_traceback"].failed_by_assertion is False
    finally:
        f_path.unlink()


def test_bare_assert_without_traceback_is_still_an_assertion() -> None:
    """При отключённом трейсбеке голый assert опознаётся по самому message."""
    xml_content = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="0" failures="1" skipped="0" tests="1" time="0.1">
<testcase classname="tests.test_x" name="test_one" file="tests/test_x.py" time="0.0">
<failure message="assert Decimal('130.0000') == Decimal('70.0000')" /></testcase>
</testsuite></testsuites>
"""
    with tempfile.NamedTemporaryFile("w", suffix=".xml", encoding="utf-8", delete=False) as f:
        f.write(xml_content)
        f_path = Path(f.name)

    try:
        report = parse_junit(f_path)["tests/test_x.py::test_one"]
        assert report.exception_type == "AssertionError"
        assert report.failed_by_assertion is True
    finally:
        f_path.unlink()
