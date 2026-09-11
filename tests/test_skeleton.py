"""Все модули импортируются: заглушки не ломают сборку пакета, пока их реализуют параллельно."""

import importlib
import pkgutil

import harness


def test_all_modules_import() -> None:
    names = [m.name for m in pkgutil.walk_packages(harness.__path__, "harness.") if m.name != "harness.__main__"]
    assert names
    for name in names:
        importlib.import_module(name)
