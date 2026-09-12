"""LLM-мутанты: правдоподобные неправильные решения в виде патчей. Владелец: №2."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from harness.contracts import CaseDraft, Mutant, MutantSource, RepoContext, Trust
from harness.llm.client import LlmClient
from harness.llm.parsing import ParsingError, extract_json

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(filename: str) -> str:
    path = PROMPTS_DIR / filename
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return ""


def _format_context_for_mutants(context: RepoContext, draft: CaseDraft, oracle_diff: str) -> str:
    lines: list[str] = [
        "## Спецификация задачи",
        f"- Домен: {draft.spec.bank_domain}",
        f"- Цель: {draft.spec.goal}",
        f"- Краевые случаи: {draft.spec.edge_cases}",
        "",
        "## Задание для разработчика (instruction.md)",
        draft.instruction_md,
        "",
        "## Diff эталонного решения (oracle_diff)",
        oracle_diff if oracle_diff.strip() else "(дифф отсутствует; опирайся на спецификацию)",
        "",
        "## Исходные файлы проекта",
    ]

    for f in context.files[:10]:
        if f.trust == Trust.TRUSTED:
            lines.append(f"### File: {f.path}")
            lines.append(f.content)
            lines.append("")

    return "\n".join(lines)


def _normalize_patch(patch: str) -> str | None:
    """Проверяет и нормализует заголовок unified diff patch."""
    lines = patch.strip().splitlines()
    if not lines:
        return None

    # Проверяем наличие hunk
    if not any(line.startswith("@@") for line in lines):
        return None

    # Проверяем наличие удаляемых/добавляемых строк
    has_changes = any(
        (line.startswith("+") and not line.startswith("+++"))
        or (line.startswith("-") and not line.startswith("---"))
        for line in lines
    )
    if not has_changes:
        return None

    normalized_lines: list[str] = []
    for line in lines:
        if line.startswith("--- ") and not line.startswith("--- a/"):
            path = line[4:].strip().lstrip("/")
            normalized_lines.append(f"--- a/{path}")
        elif line.startswith("+++ ") and not line.startswith("+++ b/"):
            path = line[4:].strip().lstrip("/")
            normalized_lines.append(f"+++ b/{path}")
        else:
            normalized_lines.append(line)

    return "\n".join(normalized_lines) + "\n"


def _sanitize_name(name: str, index: int) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_\-]+", "-", name.strip().lower()).strip("-")
    if not cleaned:
        cleaned = f"mutant-{index}"
    if not cleaned.startswith("llm-mutant-"):
        cleaned = f"llm-mutant-{cleaned}"
    return cleaned


def write_mutants(
    client: LlmClient, context: RepoContext, draft: CaseDraft, oracle_diff: str
) -> list[Mutant]:
    """Генерирует список LLM-мутантов на основе CaseDraft и oracle_diff."""
    system_prompt = _load_prompt("mutants.md")
    user_prompt = _format_context_for_mutants(context, draft, oracle_diff)

    resp = client.complete(system=system_prompt, user=user_prompt, purpose="mutants")

    try:
        data = extract_json(resp.text)
    except ParsingError as err:
        logger.warning("Initial mutants JSON parsing failed (%s), requesting repair...", err)
        repair_user = (
            f"Не удалось разобрать ответ как JSON с мутантами: {err}\n"
            f"Верни СТРОГО валидный JSON-массив объектов с ключами 'name', 'description', 'patch'."
        )
        retry_resp = client.complete(
            system=system_prompt, user=repair_user, purpose="mutants:repair"
        )
        try:
            data = extract_json(retry_resp.text)
        except ParsingError:
            return []

    raw_list: list[dict[str, Any]] = []
    if isinstance(data, list):
        raw_list = [item for item in data if isinstance(item, dict)]
    elif isinstance(data, dict):
        if "mutants" in data and isinstance(data["mutants"], list):
            raw_list = [item for item in data["mutants"] if isinstance(item, dict)]
        else:
            raw_list = [data]

    mutants: list[Mutant] = []
    for idx, item in enumerate(raw_list, start=1):
        raw_name = str(item.get("name", f"mutant-{idx}"))
        name = _sanitize_name(raw_name, idx)
        description = str(item.get("description", "LLM-generated mutant patch")).strip()
        raw_patch = str(item.get("patch", "")).strip()

        norm_patch = _normalize_patch(raw_patch)
        if norm_patch is None:
            logger.debug("Skipping mutant %s: invalid or empty unified diff", name)
            continue

        mutants.append(
            Mutant(
                name=name,
                source=MutantSource.LLM,
                description=description,
                patch=norm_patch,
            )
        )

    return mutants
