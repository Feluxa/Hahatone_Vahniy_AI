#!/bin/sh
set -eu
mkdir -p /logs/verifier
printf '0\n' > /logs/verifier/reward.txt
export PYTHONDONTWRITEBYTECODE=1
export REPO_PATH=/app/repo
if python -m pytest --rootdir=/ /tests/test_interval.py -v -p no:cacheprovider \
    --junitxml=/logs/verifier/tests.xml > /logs/verifier/pytest.log 2>&1; then
    python - <<'PY'
from pathlib import Path
from xml.etree import ElementTree

root = ElementTree.parse('/logs/verifier/tests.xml').getroot()
cases = root.findall('.//testcase')
if len(cases) == 5 and all(
    not any(case.find(tag) is not None for tag in ('failure', 'error', 'skipped'))
    for case in cases
):
    Path('/logs/verifier/reward.txt').write_text('1\n')
PY
fi
cat /logs/verifier/pytest.log
