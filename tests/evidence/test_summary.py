import json
import tempfile
from pathlib import Path

from harness.contracts import RunKind, RunResult, RunScope, Verdict
from harness.evidence.summary import write_summary
from harness.serde import from_dict


def test_write_summary_creates_valid_json() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        evidence_dir = Path(tmp) / "evidence"

        runs = [
            RunResult(
                name="base/full",
                kind=RunKind.BASE,
                scope=RunScope.FULL,
                executed=True,
                commands=["sh /tests/test.sh"],
                image_digest="sha256:abc",
                duration_sec=12.3,
                exit_code=0,
                reward=0,
                report_path="base/full/verifier/tests.xml",
                log_dir="base/full",
                tests={},
            )
        ]
        verdict = Verdict(ok=True, problems=[], runs=["base/full"])

        path = write_summary(evidence_dir, runs, verdict)
        assert path.exists()
        assert path.name == "summary.json"

        data = json.loads(path.read_text(encoding="utf-8"))
        assert "runs" in data
        assert len(data["runs"]) == 1
        assert data["runs"][0]["name"] == "base/full"

        # Проверка обратной десериализации
        deserialized_run = from_dict(RunResult, data["runs"][0])
        assert deserialized_run.name == "base/full"
        assert deserialized_run.reward == 0


def test_write_mutant_discards_records_reason(tmp_path: Path) -> None:
    """Отброшенный мутант виден в уликах: проверки, которой нет в evidence, не существует."""
    from harness.evidence.summary import write_mutant_discards

    path = write_mutant_discards(tmp_path / "evidence", [
        {
            "name": "llm-mutant-x", "source": "llm", "stage": "generation",
            "reason": "duplicate_hunk_revert", "details": "дублирует откат эталона",
        },
        {
            "name": "mutant/llm-mutant-y", "stage": "run",
            "reason": "duplicate_outcome", "details": "роняет те же тесты, что mutant/hunk-1",
        },
    ])

    data = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "mutants_discarded.json"
    assert [d["reason"] for d in data["discarded"]] == ["duplicate_hunk_revert", "duplicate_outcome"]
    assert data["discarded"][1]["name"] == "mutant/llm-mutant-y"
