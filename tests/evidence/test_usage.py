import json
import tempfile
from pathlib import Path

from harness.contracts import LlmCall, UsageLog
from harness.evidence.usage import write_usage
from harness.serde import from_dict


def test_write_usage_creates_valid_json() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        evidence_dir = Path(tmp) / "evidence"

        calls = [
            LlmCall(
                model="GigaChat-2-Max",
                duration_sec=3.4,
                input_tokens=1500,
                output_tokens=420,
                purpose="spec",
            ),
            LlmCall(
                model="GigaChat-2-Max",
                duration_sec=5.1,
                input_tokens=2200,
                output_tokens=850,
                purpose="tests",
            ),
        ]
        usage = UsageLog(calls=calls)

        path = write_usage(evidence_dir, usage)
        assert path.exists()
        assert path.name == "llm_usage.json"

        data = json.loads(path.read_text(encoding="utf-8"))
        assert "calls" in data
        assert len(data["calls"]) == 2
        assert data["calls"][0]["model"] == "GigaChat-2-Max"
        assert data["calls"][0]["purpose"] == "spec"

        # Десериализация
        deserialized = from_dict(UsageLog, data)
        assert len(deserialized.calls) == 2
        assert deserialized.calls[0].input_tokens == 1500
        assert deserialized.calls[1].output_tokens == 850

