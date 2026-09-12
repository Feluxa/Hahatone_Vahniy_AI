"""Генерация solution/solve.sh. Владелец: №2."""
from __future__ import annotations

from harness.contracts import CaseSpec, RepoContext
import json
import logging
import re
from pathlib import Path

from harness.contracts import Trust
from harness.llm.client import LlmClient
from harness.llm.parsing import ParsingError, extract_json

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(filename: str) -> str:
    path = PROMPTS_DIR / filename
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return ""


def _format_context_for_solution(context: RepoContext, spec: CaseSpec) -> str:
    lines: list[str] = [
        "## Спецификация дефекта и задачи",
        f"- Домен: {spec.bank_domain}",
        f"- Цель: {spec.goal}",
        f"- Описание: {spec.description}",
        f"- Гипотеза дефекта:\n{spec.defect_hypothesis}",
        "",
        "### Требования к исправлению:",
    ]
    for b in spec.behavior:
        lines.append(f"- {b}")

    lines.append("\n## Исходные файлы проекта:")
    for f in context.files:
        if f.trust == Trust.TRUSTED:
            lines.append(f"### File: {f.path}")
            lines.append(f.content)
            lines.append("")

    return "\n".join(lines)


def _build_solve_sh_from_modifications(modifications: list[dict[str, str]]) -> str:
    """Генерирует надежный POSIX-совместимый solve.sh с проверкой единственности вхождения якорей."""
    mods_json = json.dumps(modifications, ensure_ascii=False, indent=2)

    script = f"""#!/bin/sh
set -eu

python - <<'PY'
import json
import os
from pathlib import Path

repo_path = Path(os.environ.get("REPO_PATH", "/app/repo"))
modifications = {mods_json}

for mod in modifications:
    file_path_str = mod["file_path"].replace("\\\\", "/").lstrip("/")
    target_file = repo_path / file_path_str
    if not target_file.is_file():
        raise SystemExit(f"Target file does not exist: {{target_file}}")

    content = target_file.read_text(encoding="utf-8")
    anchor = mod["anchor"]
    replacement = mod["replacement"]

    count = content.count(anchor)
    if count != 1:
        raise SystemExit(
            f"Expected exactly 1 occurrence of '{{anchor}}' in {{file_path_str}}, found {{count}}"
        )

    patched = content.replace(anchor, replacement, 1)
    target_file.write_text(patched, encoding="utf-8")
    print(f"Successfully patched {{file_path_str}}")
PY
"""
    return script


def _validate_solve_sh(script: str) -> list[str]:
    """Проверяет solve.sh на нарушения PROTOCOL.md."""
    problems: list[str] = []
    lower = script.lower()

    if "/tests" in lower or "task/tests" in lower:
        problems.append("solve.sh is strictly forbidden from referencing /tests")

    if "reward.txt" in lower or "/logs/verifier" in lower:
        problems.append("solve.sh is strictly forbidden from writing reward.txt")

    if not script.strip().startswith("#!"):
        problems.append("solve.sh must start with a shebang (e.g. #!/bin/sh)")

    return problems


def write_solution(client: LlmClient, context: RepoContext, spec: CaseSpec) -> dict[str, str]:
    """Генерирует solution/solve.sh на основе RepoContext и CaseSpec."""
    system_prompt = _load_prompt("solution.md")
    user_prompt = _format_context_for_solution(context, spec)

    resp = client.complete(system=system_prompt, user=user_prompt, purpose="solution")

    try:
        data = extract_json(resp.text)
    except ParsingError as err:
        logger.warning("Initial solution JSON parsing failed (%s), requesting repair...", err)
        repair_user = (
            f"Не удалось разобрать ответ как JSON решения: {err}\n"
            f"Верни СТРОГО валидный JSON-объект с ключом 'modifications' (список объектов с "
            f"'file_path', 'anchor', 'replacement') или 'solve_sh'."
        )
        retry_resp = client.complete(
            system=system_prompt, user=repair_user, purpose="solution:repair"
        )
        data = extract_json(retry_resp.text)

    # Обработка готового solve_sh либо формирование из modifications
    solve_sh_raw = data.get("solve_sh")
    modifications = data.get("modifications")

    if modifications and isinstance(modifications, list):
        clean_mods: list[dict[str, str]] = []
        for mod in modifications:
            if isinstance(mod, dict) and "file_path" in mod and "anchor" in mod and "replacement" in mod:
                clean_mods.append({
                    "file_path": str(mod["file_path"]).strip(),
                    "anchor": str(mod["anchor"]),
                    "replacement": str(mod["replacement"]),
                })
        script_content = _build_solve_sh_from_modifications(clean_mods)
    elif solve_sh_raw and isinstance(solve_sh_raw, str):
        script_content = solve_sh_raw.strip()
    else:
        # Fallback: пробуем извлечь код скрипта из fenced-блока
        sh_match = re.search(r"```(?:sh|bash)?\n(.*?)\n```", resp.text, re.DOTALL)
        if sh_match:
            script_content = sh_match.group(1).strip()
        else:
            raise ParsingError("Neither 'modifications' nor valid 'solve_sh' found in model response")

    # Валидация безопасности solve.sh
    problems = _validate_solve_sh(script_content)
    if problems:
        logger.warning("Forbidden patterns in solve.sh (%s), requesting repair...", problems)
        repair_prompt = (
            f"В сгенерированном решении обнаружены запрещенные действия ({problems}).\n"
            f"Напоминание правил:\n"
            f"1. solve.sh должен модифицировать ТОЛЬКО /app/repo.\n"
            f"2. Категорически запрещено упоминать /tests или писать reward.txt.\n"
            f"Перепиши решение корректно в виде JSON с ключом 'modifications'."
        )
        retry_resp = client.complete(
            system=system_prompt, user=repair_prompt, purpose="solution:repair"
        )
        retry_data = extract_json(retry_resp.text)
        retry_mods = retry_data.get("modifications", [])
        if retry_mods and isinstance(retry_mods, list):
            script_content = _build_solve_sh_from_modifications(retry_mods)
        else:
            script_content = retry_data.get("solve_sh", script_content)

    return {"solve.sh": script_content}
