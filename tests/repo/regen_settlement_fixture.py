"""Перегенерация fixtures/repo_context.settlement.json.

Фикстура — вывод build_context на meridian с брифом settlement-001; №2 работает по ней, а не по
репозиторию. Тест tests/repo/test_context.py сравнивает её с текущим выводом, поэтому после любой
правки эвристики отбора запустите:

    .venv/Scripts/python.exe -m tests.repo.regen_settlement_fixture
"""

from __future__ import annotations

import json
from pathlib import Path

from harness.repo.context import build_context
from harness.serde import dump_json

ROOT = Path(__file__).resolve().parents[2]
MERIDIAN = ROOT / "materials" / "hackathon-participants" / "meridian"
SETTLEMENT_INPUT = ROOT / "materials" / "hackathon-participants" / "inputs" / "settlement.json"
FIXTURE = ROOT / "fixtures" / "repo_context.settlement.json"


def main() -> None:
    if not MERIDIAN.is_dir():
        raise SystemExit(f"нет репозитория {MERIDIAN}: materials/ не выложены локально")
    brief = json.loads(SETTLEMENT_INPUT.read_text(encoding="utf-8"))["brief"]
    context = build_context(MERIDIAN, brief)
    dump_json(context, FIXTURE)
    print(f"{FIXTURE.relative_to(ROOT).as_posix()}: {len(context.files)} файлов, "
          f"{len(context.python_symbols)} символов, {len(context.sql_objects)} SQL-объектов")


if __name__ == "__main__":
    main()
