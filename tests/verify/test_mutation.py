import tempfile
from pathlib import Path

from harness.contracts import MutantSource
from harness.verify.mutation import hunk_revert_mutants, oracle_diff


def test_oracle_diff_computes_difference() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_p = Path(tmp)
        base = tmp_p / "base"
        oracle = tmp_p / "oracle"
        base.mkdir()
        oracle.mkdir()

        (base / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (oracle / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

        (base / "same.py").write_text("print('same')\n", encoding="utf-8")
        (oracle / "same.py").write_text("print('same')\n", encoding="utf-8")

        diff = oracle_diff(base, oracle)
        assert "--- a/calc.py" in diff
        assert "+++ b/calc.py" in diff
        assert "-    return a - b" in diff
        assert "+    return a + b" in diff
        assert "same.py" not in diff


def test_hunk_revert_mutants_generates_reverse_patches() -> None:
    diff_text = """--- a/services/netting.py
+++ b/services/netting.py
@@ -10,3 +10,3 @@
-net = purchases + refunds
+net = purchases - refunds
--- a/sql/refresh.sql
+++ b/sql/refresh.sql
@@ -42,3 +42,3 @@
-occurred_at <= v_end
+occurred_at < v_end
"""
    mutants = hunk_revert_mutants(diff_text)
    assert len(mutants) == 2

    m1 = mutants[0]
    assert m1.name == "hunk-1"
    assert m1.source == MutantSource.HUNK_REVERT
    assert "netting.py" in m1.description
    assert "-net = purchases - refunds" in m1.patch
    assert "+net = purchases + refunds" in m1.patch

    m2 = mutants[1]
    assert m2.name == "hunk-2"
    assert m2.source == MutantSource.HUNK_REVERT
    assert "refresh.sql" in m2.description
    assert "-occurred_at < v_end" in m2.patch
    assert "+occurred_at <= v_end" in m2.patch
