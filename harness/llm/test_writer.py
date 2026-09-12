"""Генерация тестов и трёх списков. Владелец: №2. Образец качества: golden/settlement-001."""
from __future__ import annotations

import ast
import logging
import re
from pathlib import Path

from harness.contracts import CaseSpec, RepoContext, TestLists, Trust
from harness.llm.client import LlmClient
from harness.llm.parsing import ParsingError, extract_json

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(filename: str) -> str:
    path = PROMPTS_DIR / filename
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return ""


def _format_context_and_spec_for_tests(context: RepoContext, spec: CaseSpec) -> str:
    lines: list[str] = [
        "## Спецификация кейса",
        f"- Домен: {spec.bank_domain}",
        f"- Описание: {spec.description}",
        f"- Цель: {spec.goal}",
        "",
        "### Требования к поведению:",
    ]
    for b in spec.behavior:
        lines.append(f"  * {b}")

    lines.append("\n### Краевые случаи:")
    for ec in spec.edge_cases:
        lines.append(f"  * {ec}")

    lines.append("\n### Инварианты (для anti_cheat тестов):")
    for inv in spec.invariants:
        lines.append(f"  * {inv}")

    lines.append(f"\n### Гипотеза дефекта (для fail_to_pass тестов):\n{spec.defect_hypothesis}\n")

    lines.append("## Контекст репозитория")
    lines.append(f"- Python: {context.run_profile.python_version}")
    lines.append(f"- PostgreSQL major: {context.run_profile.postgres_major}")
    lines.append(f"- Pytest pythonpath: {context.run_profile.pytest_pythonpath}")

    if context.untrusted_paths or context.injection_targets:
        lines.append("\n### Защищаемые и недоверенные файлы (для anti_cheat тестов):")
        for p in sorted(set(context.untrusted_paths + context.injection_targets)):
            lines.append(f"- {p}")

    if context.python_symbols:
        lines.append("\n### Символы Python:")
        for sym in context.python_symbols[:25]:
            lines.append(f"- {sym.kind} {sym.qualname}{sym.signature} ({sym.path})")

    if context.sql_objects:
        lines.append("\n### Объекты SQL:")
        for sql in context.sql_objects[:25]:
            lines.append(f"- {sql.kind} {sql.qualname} ({sql.path})")

    if context.files:
        lines.append("\n### Файлы проекта:")
        for f in context.files[:10]:
            if f.trust == Trust.TRUSTED:
                lines.append(f"#### File: {f.path}")
                lines.append(f.content)
                lines.append("")

    return "\n".join(lines)


def _extract_test_functions_from_ast(code: str) -> list[str]:
    """Извлекает все имена функций test_* на верхнем уровне модуля через AST."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    funcs: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                funcs.append(node.name)
    return funcs


def _normalize_test_id(raw_id: str, default_filename: str) -> str:
    """Приводит сырой идентификатор к каноническому виду tests/<filename>::<test_name>."""
    cleaned = raw_id.strip()
    if "::" in cleaned:
        path_part, func_part = cleaned.split("::", 1)
        path_part = path_part.strip().replace("\\", "/")
        filename = path_part.split("/")[-1]
        return f"tests/{filename}::{func_part.strip()}"

    func_match = re.search(r"\b(test_[a-zA-Z0-9_]+)\b", cleaned)
    if func_match:
        return f"tests/{default_filename}::{func_match.group(1)}"

    return f"tests/{default_filename}::{cleaned}"


def _align_and_validate_tests(
    test_files: dict[str, str],
    f2p_raw: list[str],
    p2p_raw: list[str],
    ac_raw: list[str],
) -> tuple[dict[str, str], TestLists]:
    """Сверяет списки с AST-деревом файлов тестов, гарантируя отсутствие дублей и пропусков."""
    # Определяем имя основного тестового файла
    primary_filename = next(iter(test_files.keys()), "test_cases.py")
    test_code = test_files.get(primary_filename, "")

    ast_funcs = _extract_test_functions_from_ast(test_code)
    ast_funcs_set = set(ast_funcs)

    def process_list(raw_items: list[str]) -> list[str]:
        result: list[str] = []
        for item in raw_items:
            norm = _normalize_test_id(item, primary_filename)
            func_name = norm.split("::")[-1]
            if not ast_funcs_set or func_name in ast_funcs_set:
                if norm not in result:
                    result.append(norm)
        return result

    f2p = process_list(f2p_raw)
    p2p = process_list(p2p_raw)
    ac = process_list(ac_raw)

    # Устраняем пересечения: f2p > ac > p2p
    f2p_set = set(f2p)
    ac = [x for x in ac if x not in f2p_set]
    ac_set = set(ac)
    p2p = [x for x in p2p if x not in f2p_set and x not in ac_set]

    # Проверяем нераспределенные функции из AST
    assigned_funcs = {x.split("::")[-1] for x in (*f2p, *p2p, *ac)}
    for func in ast_funcs:
        if func not in assigned_funcs:
            canon_id = f"tests/{primary_filename}::{func}"
            lower = func.lower()
            if any(k in lower for k in ("cheat", "isolation", "schema", "sentinel", "signature", "untrusted")):
                ac.append(canon_id)
            elif any(k in lower for k in ("refund", "defect", "fail", "boundary", "close_window")):
                f2p.append(canon_id)
            else:
                p2p.append(canon_id)

    return test_files, TestLists(fail_to_pass=f2p, pass_to_pass=p2p, anti_cheat=ac)


def write_tests(
    client: LlmClient, context: RepoContext, spec: CaseSpec
) -> tuple[dict[str, str], TestLists]:
    """Генерирует файлы тестов и три списка (fail_to_pass, pass_to_pass, anti_cheat)."""
    system_prompt = _load_prompt("tests.md")
    user_prompt = _format_context_and_spec_for_tests(context, spec)

    resp = client.complete(system=system_prompt, user=user_prompt, purpose="tests")

    try:
        data = extract_json(resp.text)
    except ParsingError as err:
        logger.warning("Initial tests JSON parsing failed (%s), requesting repair...", err)
        repair_user = (
            f"Не удалось разобрать ответ как JSON с тестами: {err}\n"
            f"Верни СТРОГО валидный JSON-объект со следующими ключами:\n"
            f"- test_file_name (например, 'test_settlement_close.py')\n"
            f"- test_file_content (полный Python код тестов pytest)\n"
            f"- fail_to_pass (массив полных ID тестов)\n"
            f"- pass_to_pass (массив полных ID тестов)\n"
            f"- anti_cheat (массив полных ID тестов)"
        )
        retry_resp = client.complete(
            system=system_prompt, user=repair_user, purpose="tests:repair"
        )
        data = extract_json(retry_resp.text)

    filename = str(data.get("test_file_name", "test_settlement_close.py")).strip()
    if not filename.endswith(".py"):
        filename += ".py"

    content = str(data.get("test_file_content", "")).strip()

    # Проверяем синтаксис сгенерированного кода
    try:
        ast.parse(content)
    except SyntaxError as syntax_err:
        logger.warning("Syntax error in generated tests (%s), requesting repair...", syntax_err)
        syntax_repair_user = (
            f"В сгенерированном коде тестов обнаружена синтаксическая ошибка: {syntax_err}\n"
            f"Код был:\n{content}\n\n"
            f"Исправь синтаксическую ошибку и верни корректный валидный JSON."
        )
        retry_resp = client.complete(
            system=system_prompt, user=syntax_repair_user, purpose="tests:repair"
        )
        retry_data = extract_json(retry_resp.text)
        content = str(retry_data.get("test_file_content", content)).strip()
        data = retry_data

    f2p_raw: list[str] = [str(x) for x in data.get("fail_to_pass", [])]
    p2p_raw: list[str] = [str(x) for x in data.get("pass_to_pass", [])]
    ac_raw: list[str] = [str(x) for x in data.get("anti_cheat", [])]

    test_files = {filename: content}
    return _align_and_validate_tests(test_files, f2p_raw, p2p_raw, ac_raw)
