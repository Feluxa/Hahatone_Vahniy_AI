"""Сериализация dataclass-ов из harness.contracts в JSON и обратно.

    data = to_dict(repo_context)                 # -> dict, готов для json.dumps
    ctx = from_dict(RepoContext, data)           # -> RepoContext
    dump_json(ctx, path); load_json(RepoContext, path)

Поддерживаются: dataclass, Enum, Path, list[X], dict[str, X], X | None, простые типы.
"""

from __future__ import annotations

import dataclasses
import json
import types
import typing
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")


def to_dict(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Path):
        return obj.as_posix()
    if isinstance(obj, (list, tuple)):
        return [to_dict(item) for item in obj]
    if isinstance(obj, dict):
        return {str(key): to_dict(value) for key, value in obj.items()}
    return obj


def from_dict(cls: type[T], data: Any) -> T:
    return _convert(cls, data, path=cls.__name__)


def dump_json(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_dict(obj), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(cls: type[T], path: Path) -> T:
    return from_dict(cls, json.loads(path.read_text(encoding="utf-8")))


def _convert(tp: Any, value: Any, path: str) -> Any:
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)

    if tp is Any:
        return value
    if origin in (typing.Union, types.UnionType):
        if value is None and type(None) in args:
            return None
        errors = []
        for arg in args:
            if arg is type(None):
                continue
            try:
                return _convert(arg, value, path)
            except (TypeError, ValueError) as exc:
                errors.append(str(exc))
        raise TypeError(f"{path}: no variant of {tp} matched ({'; '.join(errors)})")
    if origin is list:
        _expect(value, list, path)
        return [_convert(args[0], item, f"{path}[{i}]") for i, item in enumerate(value)]
    if origin is dict:
        _expect(value, dict, path)
        return {key: _convert(args[1], item, f"{path}.{key}") for key, item in value.items()}
    if dataclasses.is_dataclass(tp):
        _expect(value, dict, path)
        hints = typing.get_type_hints(tp)
        known = {f.name for f in dataclasses.fields(tp)}
        unknown = set(value) - known
        if unknown:
            raise ValueError(f"{path}: unknown fields {sorted(unknown)}")
        kwargs = {
            name: _convert(hints[name], item, f"{path}.{name}")
            for name, item in value.items()
        }
        try:
            return tp(**kwargs)
        except TypeError as exc:
            raise TypeError(f"{path}: {exc}") from exc
    if isinstance(tp, type) and issubclass(tp, Enum):
        return tp(value)
    if tp is Path:
        _expect(value, str, path)
        return Path(value)
    if tp is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{path}: expected number, got {type(value).__name__}")
        return float(value)
    if tp in (int, str, bool):
        if not isinstance(value, tp) or (tp is int and isinstance(value, bool)):
            raise TypeError(f"{path}: expected {tp.__name__}, got {type(value).__name__}")
        return value
    raise TypeError(f"{path}: unsupported type {tp}")


def _expect(value: Any, kind: type, path: str) -> None:
    if not isinstance(value, kind):
        raise TypeError(f"{path}: expected {kind.__name__}, got {type(value).__name__}")
