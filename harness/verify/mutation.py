from __future__ import annotations

import difflib
import re
from pathlib import Path

from harness.contracts import Mutant, MutantSource


def oracle_diff(base_repo: Path, oracle_repo: Path) -> str:
    """Генерирует unified diff между base_repo и oracle_repo для всех файлов репозитория."""
    diff_lines: list[str] = []

    def _get_files(repo: Path) -> set[str]:
        files: set[str] = set()
        for p in repo.rglob("*"):
            if p.is_file():
                rel = p.relative_to(repo).as_posix()
                parts = rel.split("/")
                if any(part in {".git", ".venv", "__pycache__", ".pytest_cache", ".DS_Store"} for part in parts):
                    continue
                if rel.endswith(".pyc"):
                    continue
                files.add(rel)
        return files

    all_files = sorted(_get_files(base_repo) | _get_files(oracle_repo))
    for rel in all_files:
        base_file = base_repo / rel
        oracle_file = oracle_repo / rel

        base_lines = base_file.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if base_file.exists() else []
        oracle_lines = oracle_file.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if oracle_file.exists() else []

        if base_lines != oracle_lines:
            file_diff = list(difflib.unified_diff(
                base_lines,
                oracle_lines,
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
            ))
            diff_lines.extend(file_diff)

    return "".join(diff_lines)


def hunk_revert_mutants(diff: str) -> list[Mutant]:
    """Разбивает unified diff на отдельные hunks и для каждого формирует обратный патч-мутант."""
    mutants: list[Mutant] = []
    if not diff.strip():
        return mutants

    lines = diff.splitlines(keepends=True)
    i = 0
    current_file_b = ""
    current_rel = ""
    hunk_index = 0

    hunk_header_re = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@(.*)$")

    while i < len(lines):
        line = lines[i]
        if line.startswith("--- "):
            i += 1
            if i < len(lines) and lines[i].startswith("+++ "):
                current_file_b = lines[i].strip().split(maxsplit=1)[1]
                # Извлекаем относительный путь файла (убираем a/ или b/)
                current_rel = current_file_b
                if current_rel.startswith("b/") or current_rel.startswith("a/"):
                    current_rel = current_rel[2:]
                i += 1
            continue

        m = hunk_header_re.match(line.rstrip("\r\n"))
        if m and current_rel:
            hunk_index += 1
            old_start, old_len, new_start, new_len, suffix = m.groups()
            old_len_str = f",{old_len}" if old_len is not None else ""
            new_len_str = f",{new_len}" if new_len is not None else ""

            # В реверс-патче меняем местами old и new
            reverted_header = f"@@ -{new_start}{new_len_str} +{old_start}{old_len_str} @@{suffix}\n"

            hunk_body_lines: list[str] = []
            i += 1
            while i < len(lines):
                cur = lines[i]
                if cur.startswith("@@ ") or cur.startswith("--- "):
                    break
                if cur.startswith("+"):
                    hunk_body_lines.append("-" + cur[1:])
                elif cur.startswith("-"):
                    hunk_body_lines.append("+" + cur[1:])
                else:
                    hunk_body_lines.append(cur)
                i += 1

            hunk_anchor_lines = [line_item[1:] for line_item in hunk_body_lines if line_item.startswith("-")]
            hunk_replacement_lines = [line_item[1:] for line_item in hunk_body_lines if line_item.startswith("+")]
            anchor_text = "".join(hunk_anchor_lines)
            replacement_text = "".join(hunk_replacement_lines)

            patch_parts = [
                f"--- a/{current_rel}\n",
                f"+++ b/{current_rel}\n",
                reverted_header,
                *hunk_body_lines,
            ]
            mutants.append(Mutant(
                name=f"hunk-{hunk_index}",
                source=MutantSource.HUNK_REVERT,
                description=f"Revert hunk {hunk_index} in {current_rel}",
                patch="".join(patch_parts),
                file_path=current_rel,
                anchor=anchor_text,
                replacement=replacement_text,
            ))
            continue

        i += 1

    return mutants


def normalize_snippet(s: str) -> str:
    """Нормализует фрагмент кода: убирает пробелы в начале/конце строк и пустые строки."""
    return "\n".join(line.strip() for line in s.splitlines() if line.strip())


def deduplicate_mutants(
    hunk_mutants: list[Mutant], extra_mutants: list[Mutant]
) -> tuple[list[Mutant], list[str]]:
    """Отсекает дубликаты мутантов:

    1. Мутанты, дублирующие откат эталона (hunk-revert): если LLM-мутант меняет
       код решения обратно на исходный код (anchor и replacement совпадают с hunk-revert).
    2. Повторяющиеся LLM-мутанты между собой (одинаковый file_path, anchor и replacement).
    3. Мутанты без изменений (anchor совпадает с replacement).

    Возвращает (итоговый список мутантов, список сообщений об отброшенных).
    """
    kept_extra: list[Mutant] = []
    dropped_notes: list[str] = []
    seen_extra: set[tuple[str, str, str]] = set()

    # Собираем все инверсии эталона (hunk-revert)
    reverts_by_file: dict[str, list[tuple[str, str]]] = {}
    for h in hunk_mutants:
        norm_path = h.file_path.replace("\\", "/").strip("./")
        norm_anc = normalize_snippet(h.anchor)
        norm_rep = normalize_snippet(h.replacement)
        if norm_anc and norm_rep:
            reverts_by_file.setdefault(norm_path, []).append((norm_anc, norm_rep))

    for m in extra_mutants:
        norm_path = m.file_path.replace("\\", "/").strip("./")
        norm_anc = normalize_snippet(m.anchor)
        norm_rep = normalize_snippet(m.replacement)

        # 1. Пустая мутация
        if not norm_anc or not norm_rep or norm_anc == norm_rep:
            dropped_notes.append(
                f"Мутант {m.name} отброшен: пустой anchor/replacement или замена тождественна"
            )
            continue

        # 2. Дубликат другого LLM-мутанта
        key = (norm_path, norm_anc, norm_rep)
        if key in seen_extra:
            dropped_notes.append(
                f"Мутант {m.name} отброшен: дублирует другого LLM-мутанта в {m.file_path}"
            )
            continue

        # 3. Дубликат отката эталона (hunk-revert)
        is_hunk_duplicate = False
        if norm_path in reverts_by_file:
            for h_anc, h_rep in reverts_by_file[norm_path]:
                # Точное совпадение или взаимное включение
                if (norm_anc == h_anc and norm_rep == h_rep) or \
                   (norm_anc in h_anc and norm_rep in h_rep) or \
                   (h_anc in norm_anc and h_rep in norm_rep):
                    is_hunk_duplicate = True
                    break

        if is_hunk_duplicate:
            dropped_notes.append(
                f"Мутант {m.name} отброшен: дублирует откат эталонного решения (hunk-revert) в {m.file_path}"
            )
            continue

        seen_extra.add(key)
        kept_extra.append(m)

    return [*hunk_mutants, *kept_extra], dropped_notes


