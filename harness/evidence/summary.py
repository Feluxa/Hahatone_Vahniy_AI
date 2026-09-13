from __future__ import annotations

import json
from pathlib import Path

from harness.contracts import RunResult, Verdict
from harness.serde import to_dict


def write_summary(evidence_dir: Path, runs: list[RunResult], verdict: Verdict | None = None) -> Path:
    """Записывает evidence/summary.json в соответствии с PROTOCOL.md."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    summary_path = evidence_dir / "summary.json"
    data: dict[str, object] = {
        "runs": [to_dict(run) for run in runs],
    }
    if verdict is not None:
        data["verdict"] = to_dict(verdict)
    summary_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary_path



def write_mutant_discards(evidence_dir: Path, discards: list[dict[str, str]]) -> Path:
    """Записывает evidence/mutants_discarded.json — мутанты, не давшие свидетельства.

    Сверх PROTOCOL.md. Проверка, отброшенная молча, неотличима от проверки, которая
    прошла: по summary.json видно только запущенные прогоны, а отброшенный на генерации
    мутант прогона не порождает вовсе.
    """
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / "mutants_discarded.json"
    path.write_text(
        json.dumps({"discarded": discards}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
