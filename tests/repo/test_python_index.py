"""Индекс Python-символов (PLAN §5.3).

Индекс читает только те файлы, которые ему дали: отбор — дело context.py. Всё, что не разобралось
(битый синтаксис, не-UTF-8, отсутствующий путь), молча пропускается: контекст не должен падать
из-за одного файла в чужом репозитории.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.repo.python_index import find_imports, index_python
from tests.repo.tiny_repo import build_repo

MERIDIAN = Path(__file__).resolve().parents[2] / "materials" / "hackathon-participants" / "meridian"
needs_meridian = pytest.mark.skipif(not MERIDIAN.is_dir(), reason="materials/ не выложены локально")

MODULE = b'''"""Module docstring."""

from decimal import Decimal


CONSTANT = 1


def top_level(value: int, *rest: str, flag: bool = False, **extra: object) -> Decimal:
    """Top level function."""
    return Decimal(value)


def _private() -> None:
    pass


class Outer:
    """Outer class."""

    attribute: int = 0

    def __init__(self, name: str) -> None:
        self.name = name

    async def run(self, *, timeout: float) -> None:
        pass

    def _helper(self) -> None:
        pass

    class Inner(Outer):
        def ping(self):
            pass
'''


@pytest.fixture()
def module_repo(tmp_path: Path) -> Path:
    return build_repo(tmp_path, {"pkg/module.py": MODULE})


def qualnames(repo: Path, paths: list[str]) -> list[str]:
    return [symbol.qualname for symbol in index_python(repo, paths)]


def test_symbols_are_listed_in_source_order(module_repo: Path) -> None:
    assert qualnames(module_repo, ["pkg/module.py"]) == [
        "top_level", "Outer", "Outer.__init__", "Outer.run", "Outer.Inner", "Outer.Inner.ping",
    ]


def test_private_names_are_skipped_but_dunders_stay(module_repo: Path) -> None:
    found = qualnames(module_repo, ["pkg/module.py"])
    assert "_private" not in found
    assert "Outer._helper" not in found
    assert "Outer.__init__" in found


def test_function_signature_keeps_defaults_and_star_args(module_repo: Path) -> None:
    symbol = next(s for s in index_python(module_repo, ["pkg/module.py"]) if s.qualname == "top_level")
    assert symbol.kind == "function"
    assert symbol.signature == "(value: int, *rest: str, flag: bool=False, **extra: object) -> Decimal"
    assert symbol.docstring == "Top level function."
    assert symbol.path == "pkg/module.py"
    assert symbol.line == 9


def test_async_method_is_marked_in_signature(module_repo: Path) -> None:
    symbol = next(s for s in index_python(module_repo, ["pkg/module.py"]) if s.qualname == "Outer.run")
    assert symbol.kind == "method"
    assert symbol.signature == "async (self, *, timeout: float) -> None"


def test_class_signature_is_its_bases(module_repo: Path) -> None:
    symbols = {s.qualname: s for s in index_python(module_repo, ["pkg/module.py"])}
    assert symbols["Outer"].kind == "class"
    assert symbols["Outer"].signature == "()"
    assert symbols["Outer"].docstring == "Outer class."
    assert symbols["Outer.Inner"].signature == "(Outer)"
    assert symbols["Outer.Inner"].docstring is None


def test_missing_annotations_are_reported_as_written(module_repo: Path) -> None:
    symbol = next(s for s in index_python(module_repo, ["pkg/module.py"]) if s.qualname == "Outer.Inner.ping")
    assert symbol.signature == "(self)"


@pytest.mark.parametrize("content", [b"def broken(:\n", b"\xff\xfe\x00binary", b"class A:\n  def f("])
def test_unparsable_file_is_skipped(tmp_path: Path, content: bytes) -> None:
    repo = build_repo(tmp_path, {"bad.py": content, "good.py": b"def ok() -> None:\n    pass\n"})
    assert qualnames(repo, ["bad.py", "good.py"]) == ["ok"]


def test_missing_and_non_python_paths_are_skipped(module_repo: Path) -> None:
    assert index_python(module_repo, ["absent.py", "pkg/module.txt", "pkg"]) == []


IMPORT_REPO: dict[str, bytes] = {
    "src/app/service.py": (
        b"import os\n"
        b"import app.helpers.util\n"
        b"from app.models.Order import Order\n"
        b"from app.legacy import LEGACY\n"
        b"from app.nowhere.Missing import Missing\n"
        b"from .sibling import thing\n"
    ),
    "src/app/__init__.py": b"",
    "src/app/helpers/util.py": b"VALUE = 1\n",
    "src/app/models/Order.py": b"class Order:\n    pass\n",
    "src/app/legacy/__init__.py": b"LEGACY = 1\n",
    "src/app/sibling.py": b"thing = 1\n",
    "root_entry.py": b"import root_module\nimport root_entry\n",
    "root_module.py": b"VALUE = 1\n",
}


def test_imports_resolve_through_roots(tmp_path: Path) -> None:
    repo = build_repo(tmp_path, IMPORT_REPO)
    assert find_imports(repo, "src/app/service.py", ["src"]) == [
        "src/app/helpers/util.py",
        "src/app/legacy/__init__.py",
        "src/app/models/Order.py",
        "src/app/sibling.py",
    ]


def test_without_roots_only_relative_and_root_level_imports_resolve(tmp_path: Path) -> None:
    """Относительный импорт считается от самого файла и от roots не зависит; корень репозитория —
    всегда root, чтобы проект без pythonpath тоже индексировался. Сам файл в список не попадает."""
    repo = build_repo(tmp_path, IMPORT_REPO)
    assert find_imports(repo, "src/app/service.py", []) == ["src/app/sibling.py"]
    assert find_imports(repo, "root_entry.py", []) == ["root_module.py"]


def test_imports_of_unparsable_file_are_empty(tmp_path: Path) -> None:
    repo = build_repo(tmp_path, {"bad.py": b"import (\n"})
    assert find_imports(repo, "bad.py", []) == []


@needs_meridian
def test_meridian_netting_policy_signature() -> None:
    path = "backend/src/components/settlement/application/impl/services/NettingPolicy.py"
    symbol = next(s for s in index_python(MERIDIAN, [path]) if s.qualname == "NettingPolicy.build")
    assert symbol.kind == "method"
    assert symbol.signature == (
        "(self, tenant_id: str, merchant_id: str, business_date: date, currency: str,"
        " events: list[MerchantEventModel]) -> SettlementModel"
    )
    assert symbol.line == 9


@needs_meridian
def test_meridian_preview_query_imports_stay_inside_component() -> None:
    path = "backend/src/components/settlement/application/impl/queries/PreviewSettlementQuery.py"
    imported = find_imports(MERIDIAN, path, ["backend/src"])
    assert imported == [
        "backend/src/components/settlement/application/core/queries/IPreviewSettlementQuery.py",
        "backend/src/components/settlement/application/impl/services/NettingPolicy.py",
        "backend/src/components/settlement/domain/models/CloseRequestModel.py",
        "backend/src/components/settlement/domain/models/SettlementModel.py",
        "backend/src/components/settlement/infrastructure/repositories/core/IMerchantEventRepository.py",
    ]
