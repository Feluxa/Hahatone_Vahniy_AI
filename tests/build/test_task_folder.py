"""Сборка папки task/ из CaseDraft (PROTOCOL.md, раздел 3).

Папка уезжает в Linux-контейнер, а собирается на Windows, поэтому всё, что мы пишем сами, идёт
с LF: test.sh и solve.sh с CRLF в контейнере не запустятся. Копия репозитория при этом byte-in-byte,
её переводы строк трогать нельзя.

Пути из черновика приходят от LLM, поэтому проверяются: '..' или ведущий слеш увели бы запись
за пределы task_dir.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from harness.build.manifest import ManifestError, read_test_lists, render_task_toml
from harness.build.task_folder import TaskFolderError, write_task_folder
from harness.contracts import (
    Author, CaseDraft, CaseInput, CaseSpec, Difficulty, Language, Limits, RunProfile, TestLists,
)
from harness.repo.profile import detect_run_profile
from tests.repo.tiny_repo import build_repo

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "golden" / "settlement-001"
GOLDEN_REPO = GOLDEN / "environment" / "repo"
needs_golden = pytest.mark.skipif(not GOLDEN_REPO.is_dir(),
                                  reason="golden/environment/repo не собран: нет materials/")

WORKSPACE_REPO: dict[str, bytes] = {
    "app.py": b"VALUE = 1\n",
    "requirements.txt": b"pytest==9.0.2\n",
    "pyproject.toml": b"[project]\nname = \"demo\"\nrequires-python = \">=3.11\"\n",
    "sub/module.py": b"OTHER = 2\n",
    ".git/config": b"[core]\n",
    "__pycache__/app.cpython-311.pyc": b"\x00binary",
    "sub/stale.pyc": b"\x00binary",
}

LISTS = TestLists(
    fail_to_pass=["tests/test_case.py::test_broken"],
    pass_to_pass=["tests/test_case.py::test_kept"],
    anti_cheat=["tests/test_case.py::test_untouched"],
)

TEST_FILE = (
    "def test_broken() -> None:\n    assert True\n\n\n"
    "def test_kept() -> None:\n    assert True\n\n\n"
    "def test_untouched() -> None:\n    assert True\n"
)
SOLVE_SH = "#!/bin/sh\nset -eu\necho fixed\n"


def make_profile(**changes: object) -> RunProfile:
    fields: dict[str, object] = {
        "python_version": "3.11",
        "requirements_file": "requirements.txt",
        "pytest_pythonpath": ["."],
        "pytest_testpaths": ["tests"],
        "needs_postgres": False,
        "postgres_major": None,
        "migration_command": None,
        "seed_sql_files": [],
        "env_vars": {},
    }
    fields.update(changes)
    return RunProfile(**fields)  # type: ignore[arg-type]


def make_case(**changes: object) -> CaseInput:
    fields: dict[str, object] = {
        "protocol_version": "1.0",
        "repository": Path("/tmp/repo"),
        "brief": "бриф",
        "output_dir": Path("/tmp/out"),
        "case_id": "team/case-001",
        "difficulty": Difficulty.MEDIUM,
        "language": Language.RU,
        "source": "team/case-001",
        "team": "team-example",
        "author": Author(name="Участник Примеров", email="participant@example.org"),
        "limits": Limits(agent_timeout_sec=1800, verifier_timeout_sec=300, build_timeout_sec=900,
                         cpus=2, memory_mb=4096, storage_mb=10240),
        "seed": 4107,
    }
    fields.update(changes)
    return CaseInput(**fields)  # type: ignore[arg-type]


def make_spec(**changes: object) -> CaseSpec:
    fields: dict[str, object] = {
        "goal": "цель",
        "behavior": ["поведение"],
        "invariants": ["инвариант"],
        "edge_cases": ["граница"],
        "defect_hypothesis": "гипотеза",
        "bank_domain": "Расчётное закрытие",
        "description": "Починить расчёт",
    }
    fields.update(changes)
    return CaseSpec(**fields)  # type: ignore[arg-type]


def make_draft(**changes: object) -> CaseDraft:
    fields: dict[str, object] = {
        "spec": make_spec(),
        "instruction_md": "# Задание\n\nПочините расчёт.\n",
        "test_files": {"test_case.py": TEST_FILE},
        "lists": LISTS,
        "solution_files": {"solve.sh": SOLVE_SH},
    }
    fields.update(changes)
    return CaseDraft(**fields)  # type: ignore[arg-type]


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    return build_repo(tmp_path / "workspace", WORKSPACE_REPO)


def build(tmp_path: Path, workspace: Path, **changes: object) -> Path:
    task_dir = tmp_path / "out" / "task"
    write_task_folder(task_dir, make_case(), make_draft(**changes), make_profile(), workspace)
    return task_dir


def relative_files(root: Path, *, skip: str | None = None) -> set[str]:
    found = set()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if skip is None or not relative.startswith(skip):
            found.add(relative)
    return found


# ---------------------------------------------------------------------------
# Структура
# ---------------------------------------------------------------------------

def test_structure_matches_the_protocol(tmp_path: Path, workspace: Path) -> None:
    task_dir = build(tmp_path, workspace)
    assert relative_files(task_dir, skip="environment/repo/") == {
        "task.toml",
        "instruction.md",
        "environment/Dockerfile",
        "environment/requirements.txt",
        "tests/test.sh",
        "tests/conftest.py",
        "tests/test_case.py",
        "solution/solve.sh",
    }


def test_instruction_and_draft_files_keep_their_content(tmp_path: Path, workspace: Path) -> None:
    task_dir = build(tmp_path, workspace)
    assert (task_dir / "instruction.md").read_text(encoding="utf-8") == "# Задание\n\nПочините расчёт.\n"
    assert (task_dir / "tests" / "test_case.py").read_text(encoding="utf-8") == TEST_FILE
    assert (task_dir / "solution" / "solve.sh").read_text(encoding="utf-8") == SOLVE_SH


def test_manifest_is_rendered_by_manifest_module(tmp_path: Path, workspace: Path) -> None:
    """Отдельного рендера в task_folder быть не должно — иначе форматы разъедутся."""
    task_dir = build(tmp_path, workspace)
    expected = render_task_toml(make_case(), make_spec(), LISTS)
    assert (task_dir / "task.toml").read_text(encoding="utf-8") == expected
    assert read_test_lists(task_dir / "task.toml") == LISTS


def test_every_test_id_points_to_a_written_file(tmp_path: Path, workspace: Path) -> None:
    task_dir = build(tmp_path, workspace)
    lists = read_test_lists(task_dir / "task.toml")
    for test_id in lists.all_ids():
        assert (task_dir / test_id.split("::", 1)[0]).is_file()


def test_nested_draft_paths_are_created(tmp_path: Path, workspace: Path) -> None:
    draft_files = {"test_case.py": TEST_FILE, "data/rows.csv": "a,b\n1,2\n"}
    task_dir = build(tmp_path, workspace, test_files=draft_files)
    assert (task_dir / "tests" / "data" / "rows.csv").read_text(encoding="utf-8") == "a,b\n1,2\n"


# ---------------------------------------------------------------------------
# Копия репозитория и мусор
# ---------------------------------------------------------------------------

def test_repo_copy_is_clean(tmp_path: Path, workspace: Path) -> None:
    task_dir = build(tmp_path, workspace)
    assert relative_files(task_dir / "environment" / "repo") == {
        "app.py", "requirements.txt", "pyproject.toml", "sub/module.py",
    }


def test_task_dir_has_no_caches_or_git(tmp_path: Path, workspace: Path) -> None:
    task_dir = build(tmp_path, workspace)
    parts = {part for path in task_dir.rglob("*") for part in path.relative_to(task_dir).parts}
    assert {".git", "__pycache__", ".venv", ".pytest_cache"} & parts == set()
    assert list(task_dir.rglob("*.pyc")) == []


# ---------------------------------------------------------------------------
# Переводы строк
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("relative", ["tests/test.sh", "solution/solve.sh",
                                      "environment/Dockerfile"])
def test_scripts_are_written_with_lf(tmp_path: Path, workspace: Path, relative: str) -> None:
    task_dir = build(tmp_path, workspace)
    assert b"\r" not in (task_dir / relative).read_bytes()


def test_everything_we_write_ourselves_is_lf(tmp_path: Path, workspace: Path) -> None:
    """Копия репозитория не в счёт: её байты обязаны совпадать с исходником."""
    task_dir = build(tmp_path, workspace, test_files={"test_case.py": "a = 1\r\nb = 2\r\n"})
    for relative in relative_files(task_dir, skip="environment/repo/"):
        assert b"\r\n" not in (task_dir / relative).read_bytes(), relative


# ---------------------------------------------------------------------------
# Проверки перед записью
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "../evil.py", "sub/../../evil.py", "/abs.py", "\\abs.py", "C:/evil.py",
    "", "   ", ".", "..", "sub\\win.py",
])
def test_path_outside_task_dir_is_rejected(tmp_path: Path, workspace: Path, bad: str) -> None:
    with pytest.raises(TaskFolderError):
        build(tmp_path, workspace, test_files={bad: "x = 1\n"})
    assert not (tmp_path / "out" / "task").exists()


def test_solution_paths_are_checked_too(tmp_path: Path, workspace: Path) -> None:
    with pytest.raises(TaskFolderError, match=r"\.\."):
        build(tmp_path, workspace, solution_files={"solve.sh": SOLVE_SH, "../evil.sh": "x"})


def test_solve_sh_is_required(tmp_path: Path, workspace: Path) -> None:
    with pytest.raises(TaskFolderError, match="solve.sh"):
        build(tmp_path, workspace, solution_files={"patch.diff": "x"})


@pytest.mark.parametrize("name", ["test.sh", "conftest.py"])
def test_draft_cannot_replace_the_harness_templates(tmp_path: Path, workspace: Path,
                                                    name: str) -> None:
    with pytest.raises(TaskFolderError, match=name):
        build(tmp_path, workspace, test_files={"test_case.py": TEST_FILE, name: "x = 1\n"})


def test_test_id_without_a_file_is_rejected(tmp_path: Path, workspace: Path) -> None:
    lists = TestLists(fail_to_pass=["tests/test_absent.py::test_x"], pass_to_pass=[], anti_cheat=[])
    with pytest.raises(TaskFolderError, match="test_absent.py"):
        build(tmp_path, workspace, lists=lists)
    assert not (tmp_path / "out" / "task").exists()


def test_broken_lists_are_rejected_and_nothing_is_written(tmp_path: Path,
                                                          workspace: Path) -> None:
    lists = TestLists(fail_to_pass=[], pass_to_pass=["tests/test_case.py::test_kept"],
                      anti_cheat=[])
    with pytest.raises(ManifestError):
        build(tmp_path, workspace, lists=lists)
    assert not (tmp_path / "out" / "task").exists()


def test_existing_task_dir_is_rejected(tmp_path: Path, workspace: Path) -> None:
    task_dir = tmp_path / "out" / "task"
    task_dir.mkdir(parents=True)
    with pytest.raises(TaskFolderError, match="уже существует"):
        write_task_folder(task_dir, make_case(), make_draft(), make_profile(), workspace)
    assert list(task_dir.iterdir()) == []


def test_missing_workspace_repo_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        write_task_folder(tmp_path / "task", make_case(), make_draft(), make_profile(),
                          tmp_path / "absent")
    assert not (tmp_path / "task").exists()


def test_failure_midway_removes_the_unfinished_folder(tmp_path: Path, workspace: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("сборка окружения сорвалась")

    monkeypatch.setattr("harness.build.task_folder.write_environment", boom)
    task_dir = tmp_path / "out" / "task"
    with pytest.raises(RuntimeError):
        write_task_folder(task_dir, make_case(), make_draft(), make_profile(), workspace)
    assert not task_dir.exists()


# ---------------------------------------------------------------------------
# Приёмочный тест: собрать эталонный кейс №3 как черновик
# ---------------------------------------------------------------------------

GOLDEN_EXTRAS = {"README.md", ".gitkeep"}


def golden_draft() -> CaseDraft:
    manifest = tomllib.loads((GOLDEN / "task.toml").read_text(encoding="utf-8"))
    spec = make_spec(bank_domain=manifest["metadata"]["bank_domain"],
                     description=manifest["task"]["description"])
    return CaseDraft(
        spec=spec,
        instruction_md=(GOLDEN / "instruction.md").read_text(encoding="utf-8"),
        test_files={"test_settlement_close.py":
                    (GOLDEN / "tests" / "test_settlement_close.py").read_text(encoding="utf-8")},
        lists=read_test_lists(GOLDEN / "task.toml"),
        solution_files={"solve.sh": (GOLDEN / "solution" / "solve.sh").read_text(encoding="utf-8")},
    )


@needs_golden
def test_golden_case_is_reproduced_file_for_file(tmp_path: Path) -> None:
    case = make_case(case_id="hackathon/settlement-001", source="hackathon/settlement-001")
    profile = detect_run_profile(GOLDEN_REPO)
    task_dir = tmp_path / "task"
    write_task_folder(task_dir, case, golden_draft(), profile, GOLDEN_REPO)

    built = relative_files(task_dir, skip="environment/repo/")
    expected = relative_files(GOLDEN, skip="environment/repo/") - GOLDEN_EXTRAS
    assert built == expected


@needs_golden
def test_golden_repo_copy_matches(tmp_path: Path) -> None:
    case = make_case(case_id="hackathon/settlement-001", source="hackathon/settlement-001")
    task_dir = tmp_path / "task"
    write_task_folder(task_dir, case, golden_draft(), detect_run_profile(GOLDEN_REPO), GOLDEN_REPO)
    assert relative_files(task_dir / "environment" / "repo") == relative_files(GOLDEN_REPO)


@needs_golden
def test_golden_manifest_lists_survive(tmp_path: Path) -> None:
    case = make_case(case_id="hackathon/settlement-001", source="hackathon/settlement-001")
    task_dir = tmp_path / "task"
    write_task_folder(task_dir, case, golden_draft(), detect_run_profile(GOLDEN_REPO), GOLDEN_REPO)
    assert read_test_lists(task_dir / "task.toml") == read_test_lists(GOLDEN / "task.toml")


def _draft_with_protected(protected: list[str]) -> CaseDraft:
    return CaseDraft(
        spec=CaseSpec(
            goal="g", behavior=["b"], invariants=["i"], edge_cases=["e"],
            defect_hypothesis="d", bank_domain="Домен", description="desc",
        ),
        instruction_md="# Задание\n",
        test_files={"test_case.py": "def test_x():\n    assert True\n"},
        lists=TestLists(fail_to_pass=["tests/test_case.py::test_x"], pass_to_pass=[], anti_cheat=[]),
        solution_files={"solve.sh": "#!/bin/sh\nset -eu\n"},
        protected_files=protected,
    )


def _repo_with_crlf(root: Path) -> Path:
    repo = root / "repo"
    (repo / "DOCS").mkdir(parents=True)
    (repo / "sql").mkdir(parents=True)
    # Тот же файл, что сторожит anti_cheat у meridian: в нём настоящие CRLF.
    (repo / "DOCS" / "release_sentinel.txt").write_bytes(b"LINE_ONE\r\nSENTINEL_OK\r\n")
    (repo / "sql" / "release_sentinel.txt").write_bytes(b"-- another file, same basename\n")
    return repo


def test_protected_file_is_copied_byte_for_byte(tmp_path: Path) -> None:
    """Эталон обязан совпадать с копией репозитория побайтно, включая CRLF."""
    repo = _repo_with_crlf(tmp_path)
    task_dir = tmp_path / "task"

    write_task_folder(
        task_dir, make_case(), _draft_with_protected(["DOCS/release_sentinel.txt"]),
        RunProfile(python_version="3.11", requirements_file=None), repo,
    )

    expected = task_dir / "tests" / "expected" / "DOCS" / "release_sentinel.txt.expected"
    in_image = task_dir / "environment" / "repo" / "DOCS" / "release_sentinel.txt"
    assert expected.read_bytes() == b"LINE_ONE\r\nSENTINEL_OK\r\n"
    assert expected.read_bytes() == in_image.read_bytes()


def test_same_named_protected_files_do_not_collide(tmp_path: Path) -> None:
    """DOCS/release_sentinel.txt и sql/release_sentinel.txt — два разных эталона."""
    repo = _repo_with_crlf(tmp_path)
    task_dir = tmp_path / "task"

    write_task_folder(
        task_dir, make_case(),
        _draft_with_protected(["DOCS/release_sentinel.txt", "sql/release_sentinel.txt"]),
        RunProfile(python_version="3.11", requirements_file=None), repo,
    )

    expected_dir = task_dir / "tests" / "expected"
    docs = expected_dir / "DOCS" / "release_sentinel.txt.expected"
    sql = expected_dir / "sql" / "release_sentinel.txt.expected"
    assert docs.read_bytes() != sql.read_bytes()
    assert docs.read_bytes() == (repo / "DOCS" / "release_sentinel.txt").read_bytes()
    assert sql.read_bytes() == (repo / "sql" / "release_sentinel.txt").read_bytes()


def test_no_expected_file_is_collectable_by_pytest(tmp_path: Path) -> None:
    """Даже если защищается тестовый файл репозитория, эталон не станет .py."""
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_existing.py").write_text("def test_repo_own():\n    assert True\n", encoding="utf-8")
    task_dir = tmp_path / "task"

    write_task_folder(
        task_dir, make_case(), _draft_with_protected(["tests/test_existing.py"]),
        RunProfile(python_version="3.11", requirements_file=None), repo,
    )

    copied = list((task_dir / "tests" / "expected").rglob("*"))
    assert [p.name for p in copied if p.is_file()] == ["test_existing.py.expected"]
    assert not any(p.suffix == ".py" for p in copied if p.is_file())


@pytest.mark.parametrize("bad_path", [
    "../etc/passwd",
    "/etc/passwd",
    "DOCS\release_sentinel.txt",
    "нет-такого-файла.txt",
    "DOCS",
])
def test_bad_protected_path_is_a_draft_problem(tmp_path: Path, bad_path: str) -> None:
    """Плохой путь — ошибка сборки черновика, а не молча пропущенная проверка."""
    repo = _repo_with_crlf(tmp_path)
    task_dir = tmp_path / "task"

    with pytest.raises(TaskFolderError) as excinfo:
        write_task_folder(
            task_dir, make_case(), _draft_with_protected([bad_path]),
            RunProfile(python_version="3.11", requirements_file=None), repo,
        )

    assert any("protected_files" in problem for problem in excinfo.value.problems)
    assert not task_dir.exists()


def test_draft_without_protected_files_is_unchanged(tmp_path: Path) -> None:
    repo = _repo_with_crlf(tmp_path)
    task_dir = tmp_path / "task"

    write_task_folder(
        task_dir, make_case(), _draft_with_protected([]),
        RunProfile(python_version="3.11", requirements_file=None), repo,
    )

    assert not (task_dir / "tests" / "expected").exists()
