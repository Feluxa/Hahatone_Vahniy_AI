"""Индекс Python-символов через ast. Владелец: №1.

Индексируются только переданные пути: что попадает в контекст, решает context.py. Приватные имена
(`_helper`) пропускаются, дандеры (`__init__`, `__call__`) остаются — по ним №2 пишет тесты.
Асинхронность видна в начале сигнатуры (`async (self, ...) -> X`), потому что отдельного поля
под неё в PythonSymbol нет, а вызывать корутину без await нельзя.

Файл, который не разобрался (битый синтаксис, не-UTF-8, отсутствующий путь), молча пропускается:
контекст не должен падать из-за одного файла в чужом репозитории.
"""
from __future__ import annotations

import ast
from pathlib import Path

from harness.contracts import PythonSymbol

MAX_SCAN_BYTES = 1 << 20

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


def index_python(repo: Path, paths: list[str]) -> list[PythonSymbol]:
    """Символы файлов в том порядке, в каком переданы пути; внутри файла — в порядке исходника."""
    symbols: list[PythonSymbol] = []
    for relative_path in paths:
        tree = _parse(repo, relative_path)
        if tree is None:
            continue
        _collect(tree.body, relative_path, prefix="", symbols=symbols)
    return symbols


def find_imports(repo: Path, path: str, roots: list[str]) -> list[str]:
    """Пути импортированных модулей, которые существуют в репозитории.

    roots — каталоги, от которых считаются абсолютные импорты (обычно RunProfile.pytest_pythonpath);
    корень репозитория добавляется всегда. Относительные импорты считаются от самого файла.
    Сам файл в результат не попадает.
    """
    tree = _parse(repo, path)
    if tree is None:
        return []
    known = [*dict.fromkeys([*roots, ""])]
    package = Path(path).parent
    found: set[str] = set()
    for node in ast.walk(tree):
        for module, level in _imported_modules(node):
            resolved = _resolve(repo, module, level, package, known)
            if resolved is not None and resolved != path:
                found.add(resolved)
    return sorted(found)


def _imported_modules(node: ast.AST) -> list[tuple[str, int]]:
    """Пары (модуль, уровень относительности). Для `from a.b import C` пробуем и `a.b.C`: имя может
    быть как классом, так и подмодулем, а по одному ast их не различить."""
    if isinstance(node, ast.Import):
        return [(alias.name, 0) for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        base = node.module or ""
        modules = [(base, node.level)] if base else []
        for alias in node.names:
            modules.append((f"{base}.{alias.name}" if base else alias.name, node.level))
        return modules
    return []


def _resolve(repo: Path, module: str, level: int, package: Path, roots: list[str]) -> str | None:
    if not module:
        return None
    parts = module.split(".")
    if level:
        base = package
        for _ in range(level - 1):
            base = base.parent
        return _existing(repo, base.joinpath(*parts))
    for root in roots:
        resolved = _existing(repo, Path(root).joinpath(*parts) if root else Path(*parts))
        if resolved is not None:
            return resolved
    return None


def _existing(repo: Path, relative: Path) -> str | None:
    for candidate in (relative.with_suffix(".py"), relative / "__init__.py"):
        if (repo / candidate).is_file():
            return candidate.as_posix()
    return None


def _parse(repo: Path, relative_path: str) -> ast.Module | None:
    if not relative_path.endswith(".py"):
        return None
    path = repo / relative_path
    try:
        if path.stat().st_size > MAX_SCAN_BYTES:
            return None
        source = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        return ast.parse(source)
    except (SyntaxError, ValueError):
        return None


def _collect(body: list[ast.stmt], path: str, prefix: str, symbols: list[PythonSymbol]) -> None:
    for node in body:
        if isinstance(node, ast.ClassDef):
            if _is_private(node.name):
                continue
            qualname = f"{prefix}{node.name}"
            symbols.append(PythonSymbol(
                path=path, kind="class", qualname=qualname, signature=_class_signature(node),
                line=node.lineno, docstring=ast.get_docstring(node),
            ))
            _collect(node.body, path, f"{qualname}.", symbols)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_private(node.name):
                continue
            symbols.append(PythonSymbol(
                path=path, kind="method" if prefix else "function", qualname=f"{prefix}{node.name}",
                signature=_function_signature(node), line=node.lineno,
                docstring=ast.get_docstring(node),
            ))


def _is_private(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _class_signature(node: ast.ClassDef) -> str:
    bases = [ast.unparse(base) for base in node.bases]
    bases += [f"{keyword.arg}={ast.unparse(keyword.value)}" for keyword in node.keywords if keyword.arg]
    return f"({', '.join(bases)})"


def _function_signature(node: FunctionNode) -> str:
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    returns = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
    return f"{prefix}({ast.unparse(node.args)}){returns}"
