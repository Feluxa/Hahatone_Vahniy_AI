#!/bin/sh
set -eu

python - <<'PY'
import os
from pathlib import Path

repo_path = Path(os.environ.get("REPO_PATH", "/app/repo"))

# 1. Исправление NettingPolicy.py (знак вычитания возвратов)
netting_file = repo_path / "backend" / "src" / "components" / "settlement" / "application" / "impl" / "services" / "NettingPolicy.py"
netting_content = netting_file.read_text(encoding="utf-8")
anchor_netting = "net = purchases + refunds"
if netting_content.count(anchor_netting) != 1:
    raise SystemExit(f"Expected exactly 1 occurrence of '{anchor_netting}' in {netting_file}")
netting_file.write_text(netting_content.replace(anchor_netting, "net = purchases - refunds"), encoding="utf-8")

# 2. Исправление 061_refresh_daily_settlement.sql (строгая граница суток)
sql_file = repo_path / "sql" / "061_refresh_daily_settlement.sql"
sql_content = sql_file.read_text(encoding="utf-8")
anchor_sql = "AND e.occurred_at <= v_end;"
if sql_content.count(anchor_sql) != 1:
    raise SystemExit(f"Expected exactly 1 occurrence of '{anchor_sql}' in {sql_file}")
sql_file.write_text(sql_content.replace(anchor_sql, "AND e.occurred_at < v_end;"), encoding="utf-8")
PY
