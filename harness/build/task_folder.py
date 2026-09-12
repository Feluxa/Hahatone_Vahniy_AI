"""Сборка папки task/ на диске из CaseDraft. Владелец: №1.

task/
  task.toml, instruction.md
  environment/Dockerfile, environment/requirements.txt (если нужен), environment/repo/ (чистая копия)
  tests/test.sh, tests/conftest.py (шаблоны №3) + test_files из черновика
  solution/solve.sh (+ solution_files)
Шаблоны окружения и тестов берутся из harness.build.environment (№3).

Манифест рендерит manifest.render_task_toml — своего рендера здесь нет, иначе форматы разъедутся.
Значит и проверки списков тестов срабатывают на сборке папки: упасть здесь лучше, чем отдать кейс
с битым task.toml.

Всё, что пишем сами, идёт с LF, включая .sh: папка собирается на Windows, а исполняется в
Linux-контейнере, где скрипт с CRLF не запустится. Копия репозитория — исключение: её байты
обязаны совпадать с исходником, от этого зависит сверка хэша снимка.

Пути из черновика приходят от LLM, поэтому проверяются до первой записи: '..', ведущий слеш или
буква диска увели бы файл за пределы task_dir. Проверки идут все разом, и task_dir создаётся
только после них; если запись всё же сорвалась, недописанная папка удаляется, как в
workspace.copy_clean.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path, PurePosixPath

from harness.build.environment import render_conftest, render_test_sh, write_environment
from harness.build.manifest import TEST_ID_SEPARATOR, render_task_toml
from harness.contracts import CaseDraft, CaseInput, RunProfile, TestLists
from harness.pytest_ids import expected_file_path
from harness.repo.workspace import copy_clean

TESTS_DIR = "tests"
SOLUTION_DIR = "solution"
ENVIRONMENT_DIR = "environment"
REPO_DIR = "repo"
SOLVE_SCRIPT = "solve.sh"

# Обвязка прогона: её пишет харнесс из шаблонов №3, черновик не имеет права её подменять.
RESERVED_TEST_FILES: frozenset[str] = frozenset({"test.sh", "conftest.py"})

WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


class TaskFolderError(ValueError):
    """Папку кейса собрать нельзя. Несёт все найденные проблемы сразу."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def write_task_folder(
    task_dir: Path, case: CaseInput, draft: CaseDraft, profile: RunProfile, workspace_repo: Path,
) -> None:
    problems: list[str] = []
    if task_dir.exists():
        problems.append(f"task_dir: уже существует, перезапись запрещена: {task_dir}")
    if not workspace_repo.is_dir():
        problems.append(f"workspace_repo: это не папка: {workspace_repo}")

    tests = _relative(draft.test_files, TESTS_DIR, problems, reserved=RESERVED_TEST_FILES)
    _relative(draft.solution_files, SOLUTION_DIR, problems)
    if SOLVE_SCRIPT not in draft.solution_files:
        problems.append(f"solution_files: нет обязательного {SOLVE_SCRIPT}")
    _check_protected_files(draft.protected_files, workspace_repo, problems)
    if problems:
        raise TaskFolderError(problems)

    # Рендер до создания папки: ManifestError не должен оставлять за собой полупустой task/.
    manifest = render_task_toml(case, draft.spec, draft.lists)
    _check_test_ids(draft.lists, tests)

    task_dir.mkdir(parents=True)
    try:
        _write(task_dir / "task.toml", manifest)
        _write(task_dir / "instruction.md", draft.instruction_md)
        _write_environment(task_dir / ENVIRONMENT_DIR, profile, workspace_repo)

        tests_dir = task_dir / TESTS_DIR
        _write(tests_dir / "test.sh", render_test_sh(draft.lists))
        _write(tests_dir / "conftest.py", render_conftest(profile, case.case_id))
        for relative_path, content in draft.test_files.items():
            _write(tests_dir / relative_path, content)
        _copy_protected(draft.protected_files, workspace_repo, tests_dir)

        for relative_path, content in draft.solution_files.items():
            _write(task_dir / SOLUTION_DIR / relative_path, content)
    except BaseException:
        shutil.rmtree(task_dir, ignore_errors=True)  # ignore_errors, чтобы не заслонить причину
        raise


def _check_protected_files(
    protected_files: list[str], workspace_repo: Path, problems: list[str],
) -> None:
    """Пути защищаемых файлов приходят от LLM, поэтому проверяются до первой записи.

    Несуществующий или уводящий за пределы репозитория путь — это проблема черновика:
    пропустить его молча нельзя, иначе anti_cheat останется без эталона, а кейс всё равно
    получит ready. TaskFolderError внутри цикла ремонта — неудачная итерация, и модель
    получит шанс назвать другой файл.
    """
    for raw in protected_files:
        problem = _path_problem(raw, frozenset())
        if problem is not None:
            problems.append(f"protected_files: {problem}: {raw!r}")
            continue
        source = workspace_repo / PurePosixPath(raw)
        if not source.is_file():
            reason = "это не обычный файл" if source.exists() else "файла нет в репозитории"
            problems.append(f"protected_files: {reason}: {raw}")


def _copy_protected(protected_files: list[str], workspace_repo: Path, tests_dir: Path) -> None:
    """Кладёт побайтные эталоны защищаемых файлов в tests/expected/.

    Именно copy2, а не _write: эталон сравнивается с файлом в /app/repo байт в байт, и любая
    нормализация переводов строк сломала бы сравнение на первом же файле с CRLF.
    """
    for raw in protected_files:
        source = workspace_repo / PurePosixPath(raw)
        target = tests_dir / PurePosixPath(expected_file_path(raw))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _write_environment(env_dir: Path, profile: RunProfile, workspace_repo: Path) -> None:
    """Dockerfile и requirements — шаблонами №3, repo/ — своей чистой копией.

    write_environment копирует репозиторий своим набором исключений; протокол (раздел 3) требует
    папку без кэшей, .git и локальных сборок, а единственное место, где этот набор описан, —
    workspace.copy_clean. Поэтому копия пересобирается ей: лишний проход по файлам дешевле, чем
    два разных ответа на вопрос «что считается мусором».
    """
    write_environment(env_dir, profile, workspace_repo)
    repo_dir = env_dir / REPO_DIR
    shutil.rmtree(repo_dir, ignore_errors=True)
    copy_clean(workspace_repo, repo_dir)
    _to_lf(env_dir / "Dockerfile")


def _relative(files: dict[str, str], label: str, problems: list[str], *,
              reserved: frozenset[str] = frozenset()) -> list[str]:
    """Проверяет пути черновика и возвращает их относительно корня task/."""
    checked: list[str] = []
    for raw in files:
        problem = _path_problem(raw, reserved)
        if problem is not None:
            problems.append(f"{label}: {problem}: {raw!r}")
            continue
        checked.append(f"{label}/{PurePosixPath(raw).as_posix()}")
    return checked


def _path_problem(raw: str, reserved: frozenset[str]) -> str | None:
    if not raw.strip():
        return "пустой путь"
    if "\\" in raw:
        return "обратный слеш в пути, ожидается POSIX-путь"
    if raw.startswith("/") or WINDOWS_DRIVE.match(raw):
        return "путь должен быть относительным"
    parts = PurePosixPath(raw).parts
    if not parts:
        return "пустой путь"
    if ".." in parts:
        return "путь выходит за пределы папки кейса"
    if raw in reserved:
        return "этот файл пишет харнесс из шаблона, подменять его нельзя"
    return None


def _check_test_ids(lists: TestLists, tests: list[str]) -> None:
    """Каждый ID из манифеста должен указывать на файл, который мы действительно кладём в task/."""
    written = {*tests, f"{TESTS_DIR}/test.sh", f"{TESTS_DIR}/conftest.py"}
    missing = sorted({
        test_id.split(TEST_ID_SEPARATOR, 1)[0]
        for test_id in lists.all_ids()
        if test_id.split(TEST_ID_SEPARATOR, 1)[0] not in written
    })
    if missing:
        raise TaskFolderError([
            f"списки тестов ссылаются на файл, которого нет в черновике: {path}"
            for path in missing
        ])


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_lf(text).encode("utf-8"))


def _to_lf(path: Path) -> None:
    """Приводит уже записанный файл к LF: Path.write_text на Windows кладёт CRLF."""
    if not path.is_file():
        return
    raw = path.read_bytes()
    normalized = raw.replace(b"\r\n", b"\n")
    if normalized != raw:
        path.write_bytes(normalized)


def _lf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")
