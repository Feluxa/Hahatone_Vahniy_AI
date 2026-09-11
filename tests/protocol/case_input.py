"""Валидный входной JSON для тестов harness/protocol.

Пути в нём относительные, как в настоящем materials/hackathon-participants/inputs/settlement.json:
так каждый тест заодно проверяет, что они разрешаются от папки входного файла.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Признак «удалить поле» для write_input: значение None было бы неотличимо от null в JSON.
MISSING = object()

REPO_DIR = "meridian"
INPUT_NAME = "inputs/case.json"
OUTPUT_DIR = "runs/case"

LIMITS: dict[str, Any] = {
    "agent_timeout_sec": 1800,
    "verifier_timeout_sec": 300,
    "build_timeout_sec": 900,
    "cpus": 2,
    "memory_mb": 4096,
    "storage_mb": 10240,
}


def base_input() -> dict[str, Any]:
    return {
        "protocol_version": "1.0",
        "repository": f"../{REPO_DIR}",
        "brief": "Устраните расхождение preview и SQL-материализации суточного закрытия.",
        "output_dir": f"../{OUTPUT_DIR}",
        "case_id": "hackathon/settlement-001",
        "difficulty": "medium",
        "language": "ru",
        "source": "hackathon/settlement-001",
        "team": "team-example",
        "author": {"name": "Участник Примеров", "email": "participant@example.org"},
        "limits": dict(LIMITS),
        "seed": 4107,
    }


def write_input(root: Path, *, encoding: str = "utf-8", **overrides: Any) -> Path:
    """Готовит <root>/meridian и пишет <root>/inputs/case.json.

    Именованные аргументы заменяют поля верхнего уровня; MISSING удаляет поле.
    """
    repository = root / REPO_DIR
    repository.mkdir(parents=True, exist_ok=True)
    (repository / "README.md").write_bytes(b"# repo\n")

    data = base_input()
    for key, value in overrides.items():
        if value is MISSING:
            data.pop(key, None)
        else:
            data[key] = value

    path = root / INPUT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding=encoding)
    return path


def limits(**overrides: Any) -> dict[str, Any]:
    """Лимиты с заменой отдельных значений: limits(cpus=0)."""
    return {**LIMITS, **overrides}
