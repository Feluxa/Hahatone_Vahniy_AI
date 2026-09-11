"""Командная строка. Владелец: №4.

    python -m harness run path/to/input.json
Код выхода: 0 — ready, 1 — failed, 2 — некорректный вход.
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness")
    sub = parser.add_subparsers(dest="command", required=True)
    run_cmd = sub.add_parser("run", help="сгенерировать кейс по входному JSON")
    run_cmd.add_argument("input", help="путь к входному JSON")
    args = parser.parse_args(argv)
    if args.command == "run":
        print("pipeline is not implemented yet", file=sys.stderr)
        return 1
    return 2
