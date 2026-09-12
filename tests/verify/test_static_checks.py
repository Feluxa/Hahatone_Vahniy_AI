import re
from pathlib import Path
from harness.contracts import ProblemCategory, TestLists
from harness.verify.static_checks import check_task_folder


def test_dirty_task_dir(tmp_path: Path):
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / ".git").mkdir()
    (task_dir / "test.log").touch()

    lists = TestLists(fail_to_pass=["tests/t.py::test_a"], pass_to_pass=[], anti_cheat=[])
    problems = check_task_folder(task_dir, lists)
    cats = {p.category for p in problems}
    assert ProblemCategory.TASK_DIR_DIRTY in cats


def test_forbidden_markers_pytest_mark_skip(tmp_path: Path):
    # Critical: @pytest.mark.skip must be detected
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    tests_dir = task_dir / "tests"
    tests_dir.mkdir()
    code = "import pytest\n\n@pytest.mark.skip\ndef test_a(): pass\n"
    (tests_dir / "test_skip.py").write_text(code)

    lists = TestLists(fail_to_pass=["tests/test_skip.py::test_a"], pass_to_pass=[], anti_cheat=[])
    problems = check_task_folder(task_dir, lists)
    cats = {p.category for p in problems}
    assert ProblemCategory.FORBIDDEN_MARKERS in cats


def test_forbidden_markers_pytest_xfail(tmp_path: Path):
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    tests_dir = task_dir / "tests"
    tests_dir.mkdir()
    code = "import pytest\n\n@pytest.mark.xfail\ndef test_b(): pass\n"
    (tests_dir / "test_xf.py").write_text(code)

    lists = TestLists(fail_to_pass=["tests/test_xf.py::test_b"], pass_to_pass=[], anti_cheat=[])
    problems = check_task_folder(task_dir, lists)
    cats = {p.category for p in problems}
    assert ProblemCategory.FORBIDDEN_MARKERS in cats


def test_instruction_leak_test_name(tmp_path: Path):
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "instruction.md").write_text("Fix the code so that test_foo works correctly.")

    lists = TestLists(fail_to_pass=["tests/test_x.py::test_foo[param1]"], pass_to_pass=[], anti_cheat=[])
    problems = check_task_folder(task_dir, lists)
    cats = {p.category for p in problems}
    assert ProblemCategory.INSTRUCTION_LEAK in cats


def test_solve_sh_detects_real_paths(tmp_path: Path):
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    sol_dir = task_dir / "solution"
    sol_dir.mkdir()
    (sol_dir / "solve.sh").write_text("cat /tests/foo.py > /logs/out.txt")

    lists = TestLists(fail_to_pass=["tests/t.py::test_a"], pass_to_pass=[], anti_cheat=[])
    problems = check_task_folder(task_dir, lists)
    cats = {p.category for p in problems}
    assert ProblemCategory.SOLUTION_TOUCHES_TESTS in cats


def test_solve_sh_no_false_positive(tmp_path: Path):
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    sol_dir = task_dir / "solution"
    sol_dir.mkdir()
    (sol_dir / "solve.sh").write_text("echo dialogs/data and attests/result")

    lists = TestLists(fail_to_pass=["tests/t.py::test_a"], pass_to_pass=[], anti_cheat=[])
    problems = check_task_folder(task_dir, lists)
    sol_problems = [p for p in problems if p.category == ProblemCategory.SOLUTION_TOUCHES_TESTS]
    assert len(sol_problems) == 0
