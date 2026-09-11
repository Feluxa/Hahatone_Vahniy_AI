import importlib.util
import inspect
import os
from pathlib import Path

import pytest

REPO = Path(os.environ.get("REPO_PATH", "/app/repo"))


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, REPO / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_right_boundary():
    module = load_module("interval")
    for start, end in [(-10, -2), (0, 1), (12, 43), (1000, 1009)]:
        assert module.contains(end, start, end) is False


def test_empty_interval():
    module = load_module("interval")
    for boundary in [-100, 0, 8, 1000]:
        assert module.contains(boundary, boundary, boundary) is False


def test_existing_membership_and_api():
    module = load_module("interval")
    assert list(inspect.signature(module.contains).parameters) == ["value", "start", "end"]
    for start, end in [(-10, -2), (0, 4), (12, 43)]:
        assert module.contains(start, start, end) is True
        assert module.contains(end - 1, start, end) is True
        assert module.contains(start - 1, start, end) is False
        assert module.contains(end + 1, start, end) is False


def test_invalid_bounds():
    module = load_module("interval")
    with pytest.raises(ValueError):
        module.contains(3, 10, 1)


def test_legacy_unchanged():
    expected = (Path(__file__).parent / "legacy.py.expected").read_bytes()
    assert (REPO / "legacy.py").read_bytes() == expected
    legacy = load_module("legacy")
    assert legacy.contains_closed(4, 1, 4) is True
    assert legacy.contains_closed(4, 4, 4) is True
