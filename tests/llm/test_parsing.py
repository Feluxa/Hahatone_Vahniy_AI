import pytest

from harness.llm.parsing import (
    ParsingError,
    extract_code_block,
    extract_files,
    extract_json,
    extract_patch,
)


def test_extract_json_pure() -> None:
    data = extract_json('{"key": "value", "num": 42}')
    assert data == {"key": "value", "num": 42}


def test_extract_json_in_markdown() -> None:
    text = """
Here is the requested specification:
```json
{
  "goal": "Fix settlement netting",
  "behavior": ["Refunds reduce total"],
  "invariants": ["Signatures unchanged"],
  "edge_cases": ["00:00 boundary"],
  "defect_hypothesis": "Plus instead of minus",
  "bank_domain": "Settlement",
  "description": "Short description"
}
```
Let me know if you need anything else!
"""
    data = extract_json(text)
    assert isinstance(data, dict)
    assert data["goal"] == "Fix settlement netting"
    assert data["behavior"] == ["Refunds reduce total"]


def test_extract_json_with_chatter_and_trailing_commas() -> None:
    text = """
The resulting structure is:
{
  "test_ids": [
    "tests/test_foo.py::test_one",
    "tests/test_foo.py::test_two",
  ],
  "flag": true,
}
That is all.
"""
    data = extract_json(text)
    assert isinstance(data, dict)
    assert len(data["test_ids"]) == 2
    assert data["flag"] is True


def test_extract_json_invalid_raises_parsing_error() -> None:
    with pytest.raises(ParsingError, match="Could not extract valid JSON"):
        extract_json("This is purely plain text without any JSON brackets or structure.")


def test_extract_json_empty_raises() -> None:
    with pytest.raises(ParsingError, match="Empty response"):
        extract_json("   \n   ")


def test_extract_files_json_dict() -> None:
    text = """
```json
{
  "tests/test_a.py": "def test_a(): pass",
  "tests/test_b.py": "def test_b(): pass"
}
```
"""
    files = extract_files(text)
    assert len(files) == 2
    assert files["tests/test_a.py"] == "def test_a(): pass"
    assert files["tests/test_b.py"] == "def test_b(): pass"


def test_extract_files_markdown_headers() -> None:
    text = """
I have created two files for you:

### File: tests/test_settlement.py
```python
import pytest

def test_refund_reduces_net():
    assert True
```

### File: solution/solve.sh
```bash
#!/bin/sh
set -eu
sed -i 's/foo/bar/' /app/repo/file.py
```
"""
    files = extract_files(text)
    assert len(files) == 2
    assert "tests/test_settlement.py" in files
    assert "def test_refund_reduces_net():" in files["tests/test_settlement.py"]
    assert "solution/solve.sh" in files
    assert "#!/bin/sh" in files["solution/solve.sh"]


def test_extract_files_inline_comment() -> None:
    text = """
```python
# tests/test_close.py
def test_close():
    pass
```
"""
    files = extract_files(text)
    assert "tests/test_close.py" in files
    assert "def test_close():" in files["tests/test_close.py"]


def test_extract_files_single_block_default_filename() -> None:
    text = """
Here is the solution script:
```bash
#!/bin/sh
sed -i 's/+/ -/' /app/repo/policy.py
```
"""
    files = extract_files(text, default_filename="solve.sh")
    assert "solve.sh" in files
    assert "sed -i" in files["solve.sh"]


def test_extract_code_block() -> None:
    text = """
Here is the instruction text:
```markdown
# Problem Description
Fix the netting issue.
```
"""
    code = extract_code_block(text)
    assert code == "# Problem Description\nFix the netting issue."

    # Без блоков кода возвращает очищенный текст
    raw = "Just simple text."
    assert extract_code_block(raw) == "Just simple text."


def test_extract_patch() -> None:
    text = """
Here is the mutant patch:
```diff
--- a/meridian/policy.py
+++ b/meridian/policy.py
@@ -10,3 +10,3 @@
-    net = purchases - refunds
+    net = purchases + refunds
```
"""
    patch = extract_patch(text)
    assert "--- a/meridian/policy.py" in patch
    assert "+++ b/meridian/policy.py" in patch
    assert "+    net = purchases + refunds" in patch

