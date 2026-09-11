#!/bin/sh
set -eu
mkdir -p /logs/verifier
printf '0\n' > /logs/verifier/reward.txt
export PYTHONDONTWRITEBYTECODE=1
export REPO_PATH=/app/repo

# Запуск pytest с junitxml
TARGETS="/tests"
if [ "$#" -gt 0 ]; then
    TARGETS="$@"
fi
if python -m pytest --rootdir=/ $TARGETS -v -p no:cacheprovider \
    --junitxml=/logs/verifier/tests.xml > /logs/verifier/pytest.log 2>&1; then
    python - <<'PY'
from pathlib import Path
from xml.etree import ElementTree

xml_path = Path('/logs/verifier/tests.xml')
if xml_path.exists():
    root = ElementTree.parse(xml_path).getroot()
    cases = root.findall('.//testcase')
    expected = int('15')
    if len(cases) == expected and all(
        not any(case.find(tag) is not None for tag in ('failure', 'error', 'skipped'))
        for case in cases
    ):
        Path('/logs/verifier/reward.txt').write_text('1\n')
PY
fi
cat /logs/verifier/pytest.log
