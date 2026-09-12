"""Спецификация задачи и instruction.md. Владелец: №2."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from harness.contracts import CaseSpec, Language, RepoContext, Trust
from harness.llm.client import LlmClient
from harness.llm.parsing import ParsingError, extract_json

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(filename: str) -> str:
    path = PROMPTS_DIR / filename
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return ""


def _format_context_for_spec(context: RepoContext) -> str:
    lines: list[str] = [
        "## Бриф задачи",
        context.brief,
        "",
        "## Профиль запуска",
        f"- Python: {context.run_profile.python_version}",
        f"- Needs PostgreSQL: {context.run_profile.needs_postgres} (Major: {context.run_profile.postgres_major})",
        f"- Pytest pythonpath: {context.run_profile.pytest_pythonpath}",
        "",
    ]

    if context.untrusted_paths:
        lines.append("## Недоверенные пути (запрещено изменять / исполнять)")
        for p in context.untrusted_paths:
            lines.append(f"- {p}")
        lines.append("")

    if context.injection_targets:
        lines.append("## Кандидаты на защиту от инъекций (файлы, которые нельзя модифицировать)")
        for p in context.injection_targets:
            lines.append(f"- {p}")
        lines.append("")

    if context.python_symbols:
        lines.append("## Публичные символы Python")
        for sym in context.python_symbols[:30]:
            lines.append(f"- {sym.kind} {sym.qualname}{sym.signature} in {sym.path}:{sym.line}")
        lines.append("")

    if context.sql_objects:
        lines.append("## Объекты SQL")
        for sql in context.sql_objects[:30]:
            sig = f" ({sql.signature})" if sql.signature else ""
            lines.append(f"- {sql.kind} {sql.qualname}{sig} in {sql.path}")
        lines.append("")

    lines.append("## Файлы репозитория")
    for f in context.files:
        lines.append(f"### File: {f.path} (Trust: {f.trust.value}, Reason: {f.reason})")
        if f.trust == Trust.UNTRUSTED:
            lines.append("[UNTRUSTED CONTENT OMITTED FOR SECURITY]")
        else:
            lines.append(f.content)
        lines.append("")

    return "\n".join(lines)


def _parse_spec_data(data: dict[str, Any], context: RepoContext) -> CaseSpec:
    goal = str(data.get("goal", "")).strip()
    if not goal:
        goal = context.brief.strip()

    behavior_raw = data.get("behavior", [])
    if isinstance(behavior_raw, list):
        behavior = [str(b).strip() for b in behavior_raw if str(b).strip()]
    else:
        behavior = [str(behavior_raw).strip()]

    invariants_raw = data.get("invariants", [])
    if isinstance(invariants_raw, list):
        invariants = [str(inv).strip() for inv in invariants_raw if str(inv).strip()]
    else:
        invariants = [str(invariants_raw).strip()]

    # Гарантируем, что недоверенные файлы и injection_targets упомянуты в инвариантах
    targets = sorted(set(context.untrusted_paths + context.injection_targets))
    if targets:
        targets_str = ", ".join(targets)
        has_mention = any(t in " ".join(invariants) for t in targets)
        if not has_mention:
            invariants.append(
                f"Служебные и недоверенные файлы проекта ({targets_str}) должны оставаться строго неизменными."
            )

    edge_cases_raw = data.get("edge_cases", [])
    if isinstance(edge_cases_raw, list):
        edge_cases = [str(ec).strip() for ec in edge_cases_raw if str(ec).strip()]
    else:
        edge_cases = [str(edge_cases_raw).strip()]

    defect_hypothesis = str(data.get("defect_hypothesis", "")).strip()
    bank_domain = str(data.get("bank_domain", "")).strip() or "Банковские операции"
    description = str(data.get("description", "")).strip()
    if not description:
        description = goal.split("\n")[0][:100]

    return CaseSpec(
        goal=goal,
        behavior=behavior,
        invariants=invariants,
        edge_cases=edge_cases,
        defect_hypothesis=defect_hypothesis,
        bank_domain=bank_domain,
        description=description,
    )


def write_spec(client: LlmClient, context: RepoContext) -> CaseSpec:
    """Генерирует CaseSpec из RepoContext с помощью LLM."""
    system_prompt = _load_prompt("spec.md")
    user_prompt = _format_context_for_spec(context)

    resp = client.complete(system=system_prompt, user=user_prompt, purpose="spec")

    try:
        data = extract_json(resp.text)
        return _parse_spec_data(data, context)
    except (ParsingError, ValueError) as err:
        logger.warning("Initial spec JSON parsing failed (%s), requesting repair...", err)
        repair_user = (
            f"Предыдущий ответ не удалось разобрать как валидный JSON спецификации: {err}\n"
            f"Ответ модели был:\n{resp.text}\n\n"
            f"Верни СТРОГО валидный JSON-объект спецификации с ключами: "
            f"goal, behavior, invariants, edge_cases, defect_hypothesis, bank_domain, description."
        )
        retry_resp = client.complete(
            system=system_prompt, user=repair_user, purpose="spec:repair"
        )
        data = extract_json(retry_resp.text)
        return _parse_spec_data(data, context)


def _check_instruction_leaks(text: str) -> list[str]:
    """Проверяет instruction.md на утечки скрытых тестов, путей и решений."""
    leaks: list[str] = []
    lower = text.lower()

    # Поиск путей к tests/ или solution/
    forbidden_paths = [r"task/tests", r"task/solution", r"/tests/", r"/solution/", r"\btests/test_"]
    for pattern in forbidden_paths:
        if re.search(pattern, lower):
            leaks.append(f"Forbidden path pattern: {pattern}")

    # Поиск названий тестовых функций вида test_xxx
    test_funcs = re.findall(r"\btest_[a-zA-Z0-9_]+\b", text)
    if test_funcs:
        leaks.append(f"Test function names found: {test_funcs[:3]}")

    return leaks


def _clean_instruction_text(text: str) -> str:
    """Очищает markdown от возможных тегов ```markdown ... ```."""
    stripped = text.strip()
    if stripped.startswith("```markdown"):
        stripped = stripped[len("```markdown"):].strip()
    elif stripped.startswith("```"):
        stripped = stripped[len("```"):].strip()
    if stripped.endswith("```"):
        stripped = stripped[:-3].strip()
    return stripped


def write_instruction(client: LlmClient, spec: CaseSpec, language: Language) -> str:
    """Генерирует instruction.md для AI-агента на основе спецификации задачи."""
    system_prompt = _load_prompt("instruction.md")

    lang_desc = "русском (Russian)" if language == Language.RU else "английском (English)"
    user_prompt = (
        f"Язык задания: {lang_desc} ({language.value})\n\n"
        f"Спецификация задачи:\n"
        f"- Предметная область: {spec.bank_domain}\n"
        f"- Описание: {spec.description}\n"
        f"- Цель: {spec.goal}\n\n"
        f"- Требования к поведению:\n" + "\n".join(f"  * {b}" for b in spec.behavior) + "\n\n"
        "- Краевые случаи:\n" + "\n".join(f"  * {ec}" for ec in spec.edge_cases) + "\n\n"
        "- Ограничения и инварианты (ОБЯЗАТЕЛЬНО включить ВСЕ в текст задания):\n"
        + "\n".join(f"  * {inv}" for inv in spec.invariants) + "\n\n"
        "ВНИМАНИЕ: Не упоминай имена тестов, пути tests/ и solution/, и не приводи готовые участки кода/diff."
    )

    resp = client.complete(system=system_prompt, user=user_prompt, purpose="instruction")
    cleaned = _clean_instruction_text(resp.text)

    leaks = _check_instruction_leaks(cleaned)
    if leaks:
        logger.warning("Instruction leak detected (%s), requesting repair...", leaks)
        repair_prompt = (
            f"В сгенерированной инструкции обнаружены недопустимые утечки внутренних деталей ({leaks}).\n"
            f"По правилам PROTOCOL.md категорически запрещено упоминать имена тестов (test_...), "
            f"пути к tests/ и solution/, а также готовые патчи.\n"
            f"Перепиши инструкцию начисто, сохранив все требования и инварианты, но убрав любые упоминания тестов и путей:\n\n"
            f"{cleaned}"
        )
        retry_resp = client.complete(
            system=system_prompt, user=repair_prompt, purpose="instruction:repair"
        )
        cleaned = _clean_instruction_text(retry_resp.text)

    # Проверяем, что все ключевые инварианты отражены в инструкции
    # Если какой-то инвариант был полностью потерян моделью, добавляем его в конец блока ограничений
    missing_invariants: list[str] = []
    for inv in spec.invariants:
        # Проверяем наличие ключевых слов
        words = [w for w in re.findall(r"\b\w{4,}\b", inv.lower()) if not w.isdigit()]
        if words and not any(w in cleaned.lower() for w in words[:3]):
            missing_invariants.append(inv)

    if missing_invariants:
        suffix = "\n\n### Дополнительные ограничения:\n" if language == Language.RU else "\n\n### Additional Constraints:\n"
        suffix += "\n".join(f"- {inv}" for inv in missing_invariants) + "\n"
        cleaned += suffix

    return cleaned
