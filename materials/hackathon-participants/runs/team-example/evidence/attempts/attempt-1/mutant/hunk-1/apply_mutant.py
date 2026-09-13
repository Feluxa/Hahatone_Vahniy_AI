import json
from pathlib import Path

spec = json.loads(Path("/logs/mutant.json").read_text(encoding="utf-8"))
target = Path("/app/repo") / spec["file_path"]
if not target.is_file():
    raise SystemExit(f"mutant target not found: {target}")
content = target.read_text(encoding="utf-8")
count = content.count(spec["anchor"])
if count != 1:
    raise SystemExit(f"anchor occurs {count} times in {spec['file_path']}, expected exactly 1")
target.write_text(content.replace(spec["anchor"], spec["replacement"], 1), encoding="utf-8")
