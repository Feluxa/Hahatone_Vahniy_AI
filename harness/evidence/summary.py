"""evidence/summary.json и раскладка логов. Владелец: №3 (перенесено с №4).

summary.json: {"runs": [...]} — для каждого прогона команды, версия окружения (digest образа), длительность,
код завершения, reward и путь к отчёту с исходом каждого теста. Невыполненные прогоны явно помечены
(executed=false) и не считаются успешными.
"""
from __future__ import annotations

from pathlib import Path

from harness.contracts import RunResult, Verdict


def write_summary(evidence_dir: Path, runs: list[RunResult], verdict: Verdict | None = None) -> Path:
    raise NotImplementedError
