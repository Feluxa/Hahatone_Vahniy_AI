"""Генерация тестов и трёх списков. Владелец: №2. Образец качества: golden/settlement-001."""
from __future__ import annotations

import ast
import logging
import re
from pathlib import Path

from harness.contracts import CaseSpec, RepoContext, TestLists, Trust
from harness.llm.client import LlmClient
from harness.llm.parsing import ParsingError, extract_json
from harness.pytest_ids import SEPARATOR, canonical_test_id, make_test_id, relative_test_path, split_test_id

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
    """Приводит сырой идентификатор к каноническому виду tests/<путь>::<test_name>.

    Путь внутри tests/ сохраняется целиком: подпапки — часть идентификатора по PROTOCOL.md.
    Идентификатор без "::" — это одно имя теста, файл берётся из default_filename.
    """
    cleaned = raw_id.strip()
    if SEPARATOR in cleaned:
        return canonical_test_id(cleaned)

    func_match = re.search(r"\b(test_[a-zA-Z0-9_]+)\b", cleaned)
    if func_match:
        return make_test_id(default_filename, func_match.group(1))

    return make_test_id(default_filename, cleaned)


def _protected_files(data: dict) -> list[str]:
    """Пути защищаемых файлов из ответа модели: только пути, без содержимого.

    Эталон для побайтного сравнения копирует сам харнесс (write_task_folder), потому что
    содержимое, переписанное моделью в JSON-строку, побайтно уже не совпадёт — в первом же
    файле с CRLF. По той же причине модель может называть и файлы из untrusted_paths:
    их содержимого она не видит, а харнессу оно и не нужно.

    Пути здесь только собираются; проверяет их write_task_folder, у которого есть репозиторий.
    Молча выбрасывать несуществующий путь нельзя — тогда anti_cheat останется без эталона.
    """
    raw = data.get("protected_files")
    if not isinstance(raw, list):
        return []
    seen: list[str] = []
    for item in raw:
        path = str(item).strip()
        if path and path not in seen:
            seen.append(path)
    return seen


def _only(candidates: list[str]) -> str | None:
    """Единственный кандидат или None. Неоднозначность — не повод молча взять первый."""
    return candidates[0] if len(candidates) == 1 else None


def _resolve_test_id(
    raw_id: str, primary_filename: str, funcs_by_file: dict[str, list[str]],
) -> str | None:
    """Канонический ID, привязанный к файлу, который действительно есть в черновике.

    Сопоставление идёт по относительному пути внутри tests/, поэтому
    'test_close.py::test_x' и 'tests/test_close.py::test_x' находят один и тот же файл.
    Модель охотно оставляет в списках имя файла из прошлой итерации, а возвращает тесты под
    новым именем: такой ID доживал до write_task_folder и ронял весь прогон, поэтому здесь он
    переотображается на файл, где функция объявлена.

    None означает «привязать не к чему»: файла нет и функция либо нигде не объявлена, либо
    объявлена сразу в нескольких файлах. Выбирать первый попавшийся нельзя — это
    несогласованность черновика, и сообщает о ней lists_inconsistent_with_files.
    """
    normalized = _normalize_test_id(raw_id, primary_filename)
    relative_path, func_name = split_test_id(normalized)

    known_funcs = funcs_by_file.get(relative_path)
    if known_funcs is not None and (not known_funcs or func_name in known_funcs):
        # Файл есть в черновике и содержит функцию. Пустой список значит, что AST не разобрался,
        # — тогда доверяем модели, как и до появления этой проверки.
        return make_test_id(relative_path, func_name)

    # Тот же файл, но лежащий в подпапке черновика.
    basename = relative_path.rsplit("/", 1)[-1]
    by_basename = _only([
        candidate for candidate in funcs_by_file
        if candidate.rsplit("/", 1)[-1] == basename
        and (not funcs_by_file[candidate] or func_name in funcs_by_file[candidate])
    ])
    if by_basename is not None:
        return make_test_id(by_basename, func_name)

    by_function = _only([
        candidate for candidate, funcs in funcs_by_file.items() if func_name in funcs
    ])
    if by_function is not None:
        return make_test_id(by_function, func_name)

    if not any(funcs_by_file.values()):
        # Ни один файл не разобрался: привязываем к основному, чтобы не потерять списки целиком.
        return make_test_id(primary_filename, func_name)
    return None


def _align_and_validate_tests(
    test_files: dict[str, str],
    f2p_raw: list[str],
    p2p_raw: list[str],
    ac_raw: list[str],
) -> tuple[dict[str, str], TestLists]:
    """Сверяет списки с AST-деревом файлов тестов, гарантируя отсутствие дублей и пропусков.

    На выходе каждый ID ссылается на файл из test_files: списки и черновик согласованы,
    и сборка папки кейса не упадёт на несуществующем файле.
    """
    # Ключи черновика — пути внутри task/tests/. Модель иногда добавляет к ним ведущий tests/,
    # и тогда файл оказывался бы в task/tests/tests/: приводим к одному виду сразу.
    test_files = {relative_test_path(name): code for name, code in test_files.items()}
    # Данные рядом с тестами (эталоны .expected, фикстуры) тестами не являются: привязывать
    # к ним идентификаторы нельзя, иначе ID уедет на файл, который pytest не собирает.
    sources = {name: code for name, code in test_files.items() if name.endswith(".py")}
    primary_filename = next(iter(sources), "test_cases.py")
    funcs_by_file: dict[str, list[str]] = {
        name: _extract_test_functions_from_ast(code) for name, code in sources.items()
    }

    def process_list(raw_items: list[str]) -> list[str]:
        result: list[str] = []
        for item in raw_items:
            resolved = _resolve_test_id(item, primary_filename, funcs_by_file)
            if resolved is not None and resolved not in result:
                result.append(resolved)
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
    assigned_ids = {*f2p, *p2p, *ac}
    for filename, funcs in funcs_by_file.items():
        for func in funcs:
            canon_id = make_test_id(filename, func)
            if canon_id in assigned_ids:
                continue
            lower = func.lower()
            if any(k in lower for k in ("cheat", "isolation", "schema", "sentinel", "signature", "untrusted")):
                ac.append(canon_id)
            elif any(k in lower for k in ("refund", "defect", "fail", "boundary", "close_window")):
                f2p.append(canon_id)
            else:
                p2p.append(canon_id)

    return test_files, TestLists(fail_to_pass=f2p, pass_to_pass=p2p, anti_cheat=ac)


def lists_inconsistent_with_files(test_files: dict[str, str], lists: TestLists) -> list[str]:
    """Проблемы согласованности списков и файлов черновика. Пустой список — всё в порядке.

    Ловится до записи на диск: иначе те же расхождения вылезут как TaskFolderError из
    write_task_folder и оборвут прогон.
    """
    problems: list[str] = []
    # Идентификатор может ссылаться только на .py: .expected и прочие данные pytest не собирает.
    known = {relative_test_path(name) for name in test_files if name.endswith(".py")}

    # Два файла с одинаковым именем в разных папках: привязать ID по имени файла к одному из них
    # нельзя, и выбирать первый попавшийся тоже — это несогласованность самого черновика.
    by_basename: dict[str, list[str]] = {}
    for name in sorted(known):
        by_basename.setdefault(name.rsplit("/", 1)[-1], []).append(name)
    for basename, paths in sorted(by_basename.items()):
        if len(paths) > 1:
            problems.append(
                f"в черновике несколько файлов с именем {basename}: {', '.join(paths)}; "
                f"идентификатор теста нельзя привязать однозначно"
            )

    missing = sorted({
        split_test_id(test_id)[0]
        for test_id in lists.all_ids()
        if split_test_id(test_id)[0] not in known
    })
    if missing:
        problems.append(
            f"списки ссылаются на файлы, которых нет в черновике: {', '.join(missing)}; "
            f"есть только {', '.join(sorted(known)) or '(ничего)'}"
        )

    non_canonical = sorted(
        test_id for test_id in lists.all_ids() if test_id != canonical_test_id(test_id)
    )
    if non_canonical:
        problems.append(
            f"идентификаторы не в каноническом виде tests/<файл>::<тест>: {', '.join(non_canonical)}"
        )
    if not lists.fail_to_pass:
        problems.append("fail_to_pass пуст: кейс без воспроизводимого дефекта не собирается")
    duplicates = lists.duplicates()
    if duplicates:
        problems.append(f"ID встречается больше одного раза: {', '.join(duplicates)}")
    return problems


def write_tests(
    client: LlmClient, context: RepoContext, spec: CaseSpec
) -> tuple[dict[str, str], TestLists, list[str]]:
    """Файлы тестов, три списка и пути защищаемых файлов для anti_cheat."""
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

    test_files, lists = _align_and_validate_tests({filename: content}, f2p_raw, p2p_raw, ac_raw)
    return test_files, lists, _protected_files(data)
