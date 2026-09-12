"""Командная строка. Владелец: №4.

    python -m harness run path/to/input.json
Код выхода: 0 — ready, 1 — failed, 2 — некорректный вход.
"""
from __future__ import annotations

import argparse
import sys
import logging
from pathlib import Path

from harness.pipeline import run
from harness.protocol.input import InputError, load_input
from harness.contracts import Status

LOGGER = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser(prog="harness")
    sub = parser.add_subparsers(dest="command", required=True)
    run_cmd = sub.add_parser("run", help="сгенерировать кейс по входному JSON")
    run_cmd.add_argument("input", help="путь к входному JSON")
    args = parser.parse_args(argv)

    if args.command == "run":
        try:
            case_input = load_input(Path(args.input))
        except InputError as e:
            print(f"Ошибка входа:\n{e}", file=sys.stderr)
            return 2

        try:
            result = run(case_input)
        except Exception:
            LOGGER.exception("Критическая ошибка пайплайна")
            return 1

        if result.status == Status.READY:
            return 0
        return 1

    return 2
