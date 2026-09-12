"""Ремонт черновика по Verdict: меняется только то, на что указывает Problem.target. Владелец: №2."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from harness.contracts import (
    CaseDraft,
    Language,
    Problem,
    RepairTarget,
    RepoContext,
    Verdict,
)
from harness.llm.client import LlmClient
from harness.llm.parsing import ParsingError, extract_json
from harness.llm.solution_writer import (
    _build_solve_sh_from_modifications,
    _validate_solve_sh,
    write_solution,
)
from harness.llm.spec_writer import (
    _check_instruction_leaks,
    _clean_instruction_text,
    write_instruction,
    write_spec,
)
from harness.llm.test_writer import (
    _align_and_validate_tests,
    write_tests,
)

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(filename: str) -> str:
    path = PROMPTS_DIR / filename
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return ""


def _format_problems(problems: list[Problem]) -> str:
    lines: list[str] = []
    for idx, p in enumerate(problems, start=1):
        tests_str = f" (tests: {', '.join(p.test_ids)})" if p.test_ids else ""
        runs_str = f" [runs: {', '.join(p.run_names)}]" if p.run_names else ""
        lines.append(f"{idx}. [{p.category.value}] target={p.target.value}: {p.details}{tests_str}{runs_str}")
    return "\n".join(lines)


def _format_log_excerpts(log_excerpts: dict[str, str]) -> str:
    if not log_excerpts:
        return "(нет доступных выжимок логов)"
    lines: list[str] = []
    for name, text in log_excerpts.items():
        snippet = text.strip()
        if len(snippet) > 2000:
            snippet = snippet[-2000:]
        lines.append(f"### Log: {name}\n{snippet}\n")
    return "\n".join(lines)


def _repair_instruction(
    client: LlmClient,
    instruction_md: str,
    problems: list[Problem],
    system_prompt: str,
) -> str:
    """Точечно устраняет утечки в instruction.md."""
    user_prompt = (
        f"Текущая инструкция (instruction.md) содержит недопустимые утечки внутренних деталей:\n"
        f"{_format_problems(problems)}\n\n"
        f"Текущий текст инструкции:\n"
        f"{instruction_md}\n\n"
        f"Перепиши инструкцию, полностью сохранив требования к функциональности и инварианты, "
        f"но удали любые упоминания имён тестов (test_*), путей tests/ и solution/, а также фрагментов кода решения. "
        f"Верни только чистый текст Markdown."
    )
    resp = client.complete(system=system_prompt, user=user_prompt, purpose="repair:instruction")
    cleaned = _clean_instruction_text(resp.text)
    leaks = _check_instruction_leaks(cleaned)
    if leaks:
        logger.warning("Instruction leaks remain after repair (%s)", leaks)
    return cleaned


def _repair_solution(
    client: LlmClient,
    context: RepoContext,
    draft: CaseDraft,
    problems: list[Problem],
    log_excerpts: dict[str, str],
    system_prompt: str,
) -> dict[str, str]:
    """Точечно исправляет solution/solve.sh."""
    current_solve_sh = draft.solution_files.get("solve.sh", "")
    user_prompt = (
        f"## Ошибки прогона решения (oracle run failed):\n"
        f"{_format_problems(problems)}\n\n"
        f"## Выжимка логов выполнения:\n"
        f"{_format_log_excerpts(log_excerpts)}\n\n"
        f"## Текущий скрипт solution/solve.sh:\n"
        f"{current_solve_sh}\n\n"
        f"## Спецификация дефекта:\n"
        f"{draft.spec.defect_hypothesis}\n\n"
        f"Сформируй исправленное решение. Верни СТРОГО валидный JSON с ключом 'modifications' "
        f"(список объектов с 'file_path', 'anchor', 'replacement') или 'solve_sh'."
    )
    resp = client.complete(system=system_prompt, user=user_prompt, purpose="repair:solution")
    try:
        data = extract_json(resp.text)
    except ParsingError:
        return draft.solution_files

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
    elif "solve_sh" in data and isinstance(data["solve_sh"], str):
        script_content = data["solve_sh"].strip()
    else:
        return draft.solution_files

    if not _validate_solve_sh(script_content):
        return {"solve.sh": script_content}
    return draft.solution_files


def _repair_tests(
    client: LlmClient,
    context: RepoContext,
    draft: CaseDraft,
    problems: list[Problem],
    log_excerpts: dict[str, str],
    system_prompt: str,
) -> tuple[dict[str, str], Any]:
    """Точечно исправляет тестовые файлы и списки."""
    primary_filename = next(iter(draft.test_files.keys()), "test_settlement_close.py")
    test_code = draft.test_files.get(primary_filename, "")

    user_prompt = (
        f"## Ошибки проверки тестов:\n"
        f"{_format_problems(problems)}\n\n"
        f"## Выжимка логов запуска pytest:\n"
        f"{_format_log_excerpts(log_excerpts)}\n\n"
        f"## Текущие списки тестов:\n"
        f"- fail_to_pass: {draft.lists.fail_to_pass}\n"
        f"- pass_to_pass: {draft.lists.pass_to_pass}\n"
        f"- anti_cheat: {draft.lists.anti_cheat}\n\n"
        f"## Текущий файл тестов ({primary_filename}):\n"
        f"{test_code}\n\n"
        f"## Спецификация дефекта:\n"
        f"{draft.spec.defect_hypothesis}\n\n"
        f"Исправь тесты и списки в соответствии с правилами PROTOCOL.md. "
        f"Верни СТРОГО валидный JSON с ключами: "
        f"test_file_name, test_file_content, fail_to_pass, pass_to_pass, anti_cheat."
    )
    resp = client.complete(system=system_prompt, user=user_prompt, purpose="repair:tests")
    try:
        data = extract_json(resp.text)
    except ParsingError:
        return draft.test_files, draft.lists

    filename = str(data.get("test_file_name", primary_filename)).strip()
    content = str(data.get("test_file_content", test_code)).strip()
    f2p_raw: list[str] = [str(x) for x in data.get("fail_to_pass", draft.lists.fail_to_pass)]
    p2p_raw: list[str] = [str(x) for x in data.get("pass_to_pass", draft.lists.pass_to_pass)]
    ac_raw: list[str] = [str(x) for x in data.get("anti_cheat", draft.lists.anti_cheat)]

    return _align_and_validate_tests({filename: content}, f2p_raw, p2p_raw, ac_raw)


def repair(
    client: LlmClient,
    context: RepoContext,
    draft: CaseDraft,
    verdict: Verdict,
    log_excerpts: dict[str, str],
) -> CaseDraft:
    """Ремонт черновика по Verdict: меняется ТОЛЬКО то, на что указывает Problem.target."""
    if verdict.ok or not verdict.problems:
        return draft

    system_prompt = _load_prompt("repair.md")

    # Группируем проблемы по целям
    problems_by_target: dict[RepairTarget, list[Problem]] = {}
    for p in verdict.problems:
        problems_by_target.setdefault(p.target, []).append(p)

    new_instruction_md = draft.instruction_md
    new_solution_files = dict(draft.solution_files)
    new_test_files = dict(draft.test_files)
    new_lists = draft.lists

    # 1. Ремонт инструкции (если есть проблемы с target=INSTRUCTION)
    if RepairTarget.INSTRUCTION in problems_by_target:
        logger.info("Repairing instruction.md...")
        new_instruction_md = _repair_instruction(
            client=client,
            instruction_md=new_instruction_md,
            problems=problems_by_target[RepairTarget.INSTRUCTION],
            system_prompt=system_prompt,
        )

    # 2. Ремонт решения (если есть проблемы с target=SOLUTION)
    if RepairTarget.SOLUTION in problems_by_target:
        logger.info("Repairing solution/solve.sh...")
        new_solution_files = _repair_solution(
            client=client,
            context=context,
            draft=draft,
            problems=problems_by_target[RepairTarget.SOLUTION],
            log_excerpts=log_excerpts,
            system_prompt=system_prompt,
        )

    # 3. Ремонт тестов (если есть проблемы с target=TESTS)
    if RepairTarget.TESTS in problems_by_target:
        logger.info("Repairing tests and lists...")
        new_test_files, new_lists = _repair_tests(
            client=client,
            context=context,
            draft=draft,
            problems=problems_by_target[RepairTarget.TESTS],
            log_excerpts=log_excerpts,
            system_prompt=system_prompt,
        )

    return CaseDraft(
        spec=draft.spec,
        instruction_md=new_instruction_md,
        test_files=new_test_files,
        lists=new_lists,
        solution_files=new_solution_files,
    )


def create_case_draft(
    client: LlmClient, context: RepoContext, language: Language = Language.RU
) -> CaseDraft:
    """Сквозной генератор полного черновика CaseDraft из контекста репозитория RepoContext."""
    logger.info("Step 1/4: Writing CaseSpec...")
    spec = write_spec(client, context)

    logger.info("Step 2/4: Writing instruction.md...")
    instruction_md = write_instruction(client, spec, language)

    logger.info("Step 3/4: Writing tests and test lists...")
    test_files, lists = write_tests(client, context, spec)

    logger.info("Step 4/4: Writing solution/solve.sh...")
    solution_files = write_solution(client, context, spec)

    return CaseDraft(
        spec=spec,
        instruction_md=instruction_md,
        test_files=test_files,
        lists=lists,
        solution_files=solution_files,
    )
