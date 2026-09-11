"""evidence/llm_usage.json: {"calls": [{model, duration_sec, input_tokens, output_tokens}]}. Владелец: №2."""
from __future__ import annotations

from pathlib import Path

from harness.contracts import UsageLog


def write_usage(evidence_dir: Path, usage: UsageLog) -> Path:
    raise NotImplementedError
