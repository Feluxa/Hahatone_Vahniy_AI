"""LLM-мутанты: правдоподобные неправильные решения в виде патчей. Владелец: №2."""
from __future__ import annotations

import logging
import re
from pathlib import PurePosixPath
from pathlib import Path
from typing import Any

from harness.contracts import CaseDraft, Mutant, MutantSource, RepoContext, Trust
from harness.llm.client import LlmClient
from harness.llm.parsing import ParsingError, extract_json

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"

# Префикс имени альтернативного решения. Ставится харнессом, а не моделью: по нему вердикт
# отличает прогон, который обязан пройти тесты, от мутанта, который обязан их провалить.
ALT_SOLUTION_NAME_PREFIX = "alt-solution-"


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


def _normalize_repo_path(raw: str) -> str:
    """Путь от модели к виду 'каталог/файл.py' — без обрезания '..'.

    Прежний lstrip('./') снимал ведущие точки посимвольно и превращал '../outside.py'
    в 'outside.py': проверка на выход за пределы /app/repo после этого уже ничего не
    находила. Снимается только явный префикс './'.
    """
    path = raw.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def _replacement_problem(file_path: str, anchor: str, replacement: str) -> str | None:
    """Почему замену нельзя применить. None — мутант годится.

    Путь приходит от модели и уезжает в контейнер, поэтому проверяется как любой другой путь
    из черновика: '..' или ведущий слеш увели бы замену за пределы /app/repo.
    """
    if not file_path:
        return "нет file_path"
    if file_path.startswith("/") or "\\" in file_path:
        return f"путь должен быть относительным POSIX-путём: {file_path!r}"
    if ".." in PurePosixPath(file_path).parts:
        return f"путь выходит за пределы /app/repo: {file_path!r}"
    if not anchor.strip():
        return "пустой anchor"
    if anchor == replacement:
        return "replacement совпадает с anchor, мутации нет"
    return None


def _sanitize_name(name: str, index: int) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_\-]+", "-", name.strip().lower()).strip("-")
    if not cleaned:
        cleaned = f"mutant-{index}"
    if not cleaned.startswith("llm-mutant-"):
        cleaned = f"llm-mutant-{cleaned}"
    return cleaned


def _request_replacement_items(
    client: LlmClient, *, system: str, user: str, purpose: str, collection_key: str,
) -> list[dict[str, Any]]:
    """Запрашивает у модели JSON-массив замен и разбирает его, с одной попыткой ремонта.

    Формат замены общий для мутантов и альтернативных решений, поэтому и разбор общий:
    массив объектов, объект с массивом внутри или одиночный объект.
    """
    resp = client.complete(system=system, user=user, purpose=purpose)

    try:
        data = extract_json(resp.text)
    except ParsingError as err:
        logger.warning("Initial %s JSON parsing failed (%s), requesting repair...", purpose, err)
        repair_user = (
            f"Не удалось разобрать ответ как JSON ({purpose}): {err}\n"
            f"Верни СТРОГО валидный JSON-массив объектов с ключами "
            f"'name', 'description', 'file_path', 'anchor', 'replacement'."
        )
        retry_resp = client.complete(
            system=system, user=repair_user, purpose=f"{purpose}:repair"
        )
        try:
            data = extract_json(retry_resp.text)
        except ParsingError:
            return []

    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        if collection_key in data and isinstance(data[collection_key], list):
            return [item for item in data[collection_key] if isinstance(item, dict)]
        return [data]
    return []


def write_mutants(
    client: LlmClient, context: RepoContext, draft: CaseDraft, oracle_diff: str
) -> list[Mutant]:
    """Генерирует список LLM-мутантов на основе CaseDraft и oracle_diff."""
    system_prompt = _load_prompt("mutants.md")
    user_prompt = _format_context_for_mutants(context, draft, oracle_diff)

    raw_list = _request_replacement_items(
        client,
        system=system_prompt,
        user=user_prompt,
        purpose="mutants",
        collection_key="mutants",
    )

    mutants: list[Mutant] = []
    for idx, item in enumerate(raw_list, start=1):
        raw_name = str(item.get("name", f"mutant-{idx}"))
        name = _sanitize_name(raw_name, idx)
        description = str(item.get("description", "LLM-generated mutant")).strip()
        file_path = _normalize_repo_path(str(item.get("file_path", "")))
        anchor = str(item.get("anchor", ""))
        replacement = str(item.get("replacement", ""))

        problem = _replacement_problem(file_path, anchor, replacement)
        if problem is not None:
            logger.warning("Мутант %s отброшен: %s", name, problem)
            continue

        mutants.append(
            Mutant(
                name=name,
                source=MutantSource.LLM,
                description=description,
                patch="",
                file_path=file_path,
                anchor=anchor,
                replacement=replacement,
            )
        )

    return mutants


def _sanitize_alt_name(name: str, index: int) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_\-]+", "-", name.strip().lower()).strip("-")
    if not cleaned:
        cleaned = f"variant-{index}"
    if not cleaned.startswith(ALT_SOLUTION_NAME_PREFIX):
        cleaned = f"{ALT_SOLUTION_NAME_PREFIX}{cleaned}"
    return cleaned


def write_alternative_solutions(
    client: LlmClient, context: RepoContext, draft: CaseDraft, oracle_diff: str, *, limit: int = 2
) -> list[Mutant]:
    """Эквивалентные переписывания эталонного решения, которые тесты обязаны принять.

    PROTOCOL §5.7: проверки принимают альтернативные корректные реализации. Мутанты
    проверяют только одну сторону — что неправильное решение отвергается; без этой
    проверки нельзя отличить тесты, проверяющие поведение, от тестов, переобученных
    на конкретный дифф эталона.

    Технически это тот же мутант-замена, что и остальные, но с expected_reward=1:
    прогон и применение уже есть, отличается только ожидание от результата.
    """
    system_prompt = _load_prompt("alternative.md")
    user_prompt = _format_context_for_mutants(context, draft, oracle_diff)

    raw_list = _request_replacement_items(
        client,
        system=system_prompt,
        user=user_prompt,
        purpose="alternatives",
        collection_key="alternatives",
    )

    variants: list[Mutant] = []
    for idx, item in enumerate(raw_list[:limit], start=1):
        name = _sanitize_alt_name(str(item.get("name", f"variant-{idx}")), idx)
        description = str(item.get("description", "LLM-generated alternative solution")).strip()
        file_path = _normalize_repo_path(str(item.get("file_path", "")))
        anchor = str(item.get("anchor", ""))
        replacement = str(item.get("replacement", ""))

        problem = _replacement_problem(file_path, anchor, replacement)
        if problem is not None:
            logger.warning("Альтернативное решение %s отброшено: %s", name, problem)
            continue

        variants.append(
            Mutant(
                name=name,
                source=MutantSource.ALTERNATIVE_SOLUTION,
                description=description,
                patch="",
                file_path=file_path,
                anchor=anchor,
                replacement=replacement,
                expected_reward=1,
            )
        )

    return variants
