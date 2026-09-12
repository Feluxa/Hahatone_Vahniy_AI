"""evidence/llm_usage.json: {"calls": [{model, duration_sec, input_tokens, output_tokens}]}. Владелец: №2."""
from __future__ import annotations

import json
from pathlib import Path

from harness.contracts import UsageLog
from harness.serde import to_dict


def write_usage(evidence_dir: Path, usage: UsageLog) -> Path:
    """Записывает evidence/llm_usage.json в соответствии с PROTOCOL.md."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    usage_path = evidence_dir / "llm_usage.json"
    data = to_dict(usage)
    usage_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return usage_path
