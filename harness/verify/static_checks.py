"""Статические проверки папки task/. Владелец: №4.

* структура task/ по протоколу, без логов, кэшей, .git, .venv;
* нет skip/xfail/skipif/importorskip в тестах;
* instruction.md не содержит имён тестов, путей tests/ и solution/, фрагментов решения;
* solve.sh не ссылается на /tests и /logs.
Сверка собранных ID со списками делается по прогону collect (verdict.py, №3).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from harness.contracts import Problem, ProblemCategory, RepairTarget, TestLists

FORBIDDEN_TASK_FILES = {".git", ".venv", "__pycache__", ".pytest_cache", ".DS_Store"}
FORBIDDEN_MARKERS = {"skip", "xfail", "skipif", "importorskip"}


def _has_pytest_root(node: ast.expr) -> bool:
    """Проверяет, что цепочка атрибутов начинается с pytest.
    Ловит: pytest.skip, pytest.mark.skip, pytest.mark.xfail и т.д.
    """
    if isinstance(node, ast.Name):
        return node.id == "pytest"
    if isinstance(node, ast.Attribute):
        return _has_pytest_root(node.value)
    return False


def _extract_test_base_name(test_id: str) -> str:
    """Извлекает имя функции из test ID, отсекая параметры.
    'tests/test_x.py::test_foo[param1]' -> 'test_foo'
    """
    func_part = test_id.split("::")[-1]
    # Отсекаем параметры pytest [...]
    bracket = func_part.find("[")
    if bracket >= 0:
        func_part = func_part[:bracket]
    return func_part


def check_task_folder(task_dir: Path, lists: TestLists) -> list[Problem]:
    problems: list[Problem] = []

    # 1. Структура task/ — без мусора
    for path in task_dir.rglob("*"):
        if path.name in FORBIDDEN_TASK_FILES or path.name.endswith(".log"):
            problems.append(
                Problem(
                    category=ProblemCategory.TASK_DIR_DIRTY,
                    target=RepairTarget.NONE,
                    details=f"Запрещённый файл/папка в task/: {path.relative_to(task_dir)}"
                )
            )

    # 2. Нет skip/xfail/skipif/importorskip в тестах
    tests_dir = task_dir / "tests"
    if tests_dir.exists():
        for test_file in tests_dir.rglob("*.py"):
            if test_file.name == "conftest.py":
                continue
            try:
                tree = ast.parse(test_file.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    # async def test_*: без pytest-asyncio такой тест не выполняется, а
                    # засчитывается пройденным — проверка получается фиктивной. Ловим до
                    # запуска контейнеров, чтобы это ушло в ремонт, а не в ложный ready.
                    if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("test_"):
                        problems.append(
                            Problem(
                                category=ProblemCategory.FORBIDDEN_MARKERS,
                                target=RepairTarget.TESTS,
                                details=(
                                    f"Асинхронный тест async def {node.name} в {test_file.name}: "
                                    f"тестовая функция должна быть синхронной, "
                                    f"асинхронный код вызывается через asyncio.run(...) внутри неё"
                                )
                            )
                        )
                    # Ловим: pytest.skip(), pytest.mark.skip, pytest.mark.xfail и т.д.
                    if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_MARKERS:
                        if _has_pytest_root(node.value):
                            problems.append(
                                Problem(
                                    category=ProblemCategory.FORBIDDEN_MARKERS,
                                    target=RepairTarget.TESTS,
                                    details=f"Запрещённый маркер pytest.*.{node.attr} в {test_file.name}"
                                )
                            )
                    # Ловим голый import: from pytest import skip
                    elif isinstance(node, ast.Name) and node.id in FORBIDDEN_MARKERS:
                        problems.append(
                            Problem(
                                category=ProblemCategory.FORBIDDEN_MARKERS,
                                target=RepairTarget.TESTS,
                                details=f"Запрещённый маркер {node.id} в {test_file.name}"
                            )
                        )
            except SyntaxError:
                pass

    # 3. instruction.md — без утечек тестов, путей и решения
    instruction_file = task_dir / "instruction.md"
    solve_sh_text = ""
    solve_sh = task_dir / "solution" / "solve.sh"
    if solve_sh.exists():
        solve_sh_text = solve_sh.read_text(encoding="utf-8")

    if instruction_file.exists():
        text = instruction_file.read_text(encoding="utf-8")

        # 3a. Пути tests/ и solution/
        if "tests/" in text or "solution/" in text:
            problems.append(
                Problem(
                    category=ProblemCategory.INSTRUCTION_LEAK,
                    target=RepairTarget.INSTRUCTION,
                    details="instruction.md ссылается на tests/ или solution/"
                )
            )

        # 3b. Имена тестов (без параметров, с границами слова)
        test_names = {_extract_test_base_name(tid) for tid in lists.all_ids()}
        leaked = [name for name in test_names if re.search(r'\b' + re.escape(name) + r'\b', text)]
        if leaked:
            problems.append(
                Problem(
                    category=ProblemCategory.INSTRUCTION_LEAK,
                    target=RepairTarget.INSTRUCTION,
                    details=f"instruction.md содержит имена тестов: {', '.join(sorted(leaked))}"
                )
            )

        # 3c. Фрагменты diff из solve.sh (строки >20 символов, без префикса + из unified diff)
        if solve_sh_text:
            for line in solve_sh_text.splitlines():
                clean = line.strip()
                # Убираем префикс unified diff (+, -)
                if clean.startswith(("+", "-")) and not clean.startswith(("+++", "---")):
                    clean = clean[1:]
                clean = clean.strip()
                if len(clean) > 20 and clean in text:
                    problems.append(
                        Problem(
                            category=ProblemCategory.INSTRUCTION_LEAK,
                            target=RepairTarget.INSTRUCTION,
                            details="instruction.md содержит фрагменты кода из решения"
                        )
                    )
                    break

    # 4. solve.sh не ссылается на /tests и /logs (точные пути, без ложных срабатываний)
    if solve_sh.exists() and solve_sh_text:
        # Ищем именно абсолютные пути /tests и /logs, а не подстроки вроде "dialogs/"
        if re.search(r'(?:^|[^a-zA-Z0-9_])/tests\b', solve_sh_text) or \
           re.search(r'(?:^|[^a-zA-Z0-9_])/logs\b', solve_sh_text):
            problems.append(
                Problem(
                    category=ProblemCategory.SOLUTION_TOUCHES_TESTS,
                    target=RepairTarget.SOLUTION,
                    details="solve.sh ссылается на /tests или /logs"
                )
            )

    return problems
