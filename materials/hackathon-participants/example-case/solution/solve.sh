#!/bin/sh
set -eu
python - <<'PY'
import os
from pathlib import Path

path = Path(os.environ.get('REPO_PATH', '/app/repo')) / 'interval.py'
source = path.read_text()
anchor = 'return start <= value <= end'
if source.count(anchor) != 1:
    raise SystemExit('Expected exactly one interval condition')
path.write_text(source.replace(anchor, 'return start <= value < end'))
PY
