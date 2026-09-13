#!/bin/sh
set -eu

python - <<'PY'
import json
import os
from pathlib import Path

repo_path = Path(os.environ.get("REPO_PATH", "/app/repo"))
modifications = [
  {
    "file_path": "backend/src/components/settlement/application/impl/services/NettingPolicy.py",
    "anchor": "net = purchases + refunds",
    "replacement": "net = purchases - refunds"
  },
  {
    "file_path": "sql/061_refresh_daily_settlement.sql",
    "anchor": "AND e.occurred_at <= v_end;",
    "replacement": "AND e.occurred_at < v_end;"
  }
]

for mod in modifications:
    file_path_str = mod["file_path"].replace("\\", "/").lstrip("/")
    target_file = repo_path / file_path_str
    if not target_file.is_file():
        raise SystemExit(f"Target file does not exist: {target_file}")

    content = target_file.read_text(encoding="utf-8")
    anchor = mod["anchor"]
    replacement = mod["replacement"]

    count = content.count(anchor)
    if count != 1:
        raise SystemExit(
            f"Expected exactly 1 occurrence of '{anchor}' in {file_path_str}, found {count}"
        )

    patched = content.replace(anchor, replacement, 1)
    target_file.write_text(patched, encoding="utf-8")
    print(f"Successfully patched {file_path_str}")
PY
