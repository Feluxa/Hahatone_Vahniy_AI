"""Сгенерированный LLM код не исполняется на хосте (решение 2.4 плана).

Единственный модуль в harness/verify/, которому разрешено запускать процессы, — docker.py:
всё остальное обязано работать через DockerRunner, то есть внутри контейнера
с --network none и лимитами кейса.
"""
import ast
import re
from pathlib import Path

VERIFY_DIR = Path(__file__).resolve().parents[2] / "harness" / "verify"

PROCESS_LAUNCH = re.compile(r"subprocess\.(?:run|Popen|call|check_output|check_call)\s*\(")
ALLOWED_TO_LAUNCH = {"docker.py"}

# docker.py:remove_image глушит ошибку удаления образа: уборка по-хорошему, отдельная находка.
KNOWN_SILENT = {"docker.py"}


def test_only_docker_module_launches_processes() -> None:
    offenders = sorted(
        path.name
        for path in VERIFY_DIR.glob("*.py")
        if path.name not in ALLOWED_TO_LAUNCH
        and PROCESS_LAUNCH.search(path.read_text(encoding="utf-8"))
    )

    assert offenders == [], (
        f"эти модули запускают процессы на хосте в обход DockerRunner: {offenders}"
    )


def test_mutation_module_does_not_touch_subprocess() -> None:
    """mutation.py — чистая работа с диффом; раньше он исполнял solve.sh на хосте."""
    source = (VERIFY_DIR / "mutation.py").read_text(encoding="utf-8")

    assert "subprocess" not in source
    assert "solve.sh" not in source


def test_verify_modules_do_not_swallow_every_exception() -> None:
    """`except Exception: pass` прятал и сбой docker, и отказ статических проверок."""
    offenders: list[str] = []
    for path in VERIFY_DIR.glob("*.py"):
        if path.name in KNOWN_SILENT:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            catches_everything = node.type is None or (
                isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"}
            )
            silent = all(isinstance(stmt, ast.Pass) for stmt in node.body)
            if catches_everything and silent:
                offenders.append(f"{path.name}:{node.lineno}")

    assert offenders == [], f"проглоченные исключения: {offenders}"
