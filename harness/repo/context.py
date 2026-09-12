"""Сбор RepoContext под бриф. Владелец: №1.

Весь репозиторий в LLM не отправляется: №2 получает 10-20 файлов, индекс символов и профиль запуска.
Отбор общий — по брифу и структуре проекта, без имён конкретного репозитория:

  1. Слова брифа (латиница и кириллица, с лёгким стеммингом) получают вес по редкости в репозитории.
     Именно вес решает главную проблему отбора без хардкода: слово, которое есть в каждом втором
     файле, почти ничего не стоит, а редкое — стоит много.
  2. Файл оценивается по совпадениям в пути (вес втрое) и в тексте.
  3. По самым сильным файлам определяется корень компонента, и соседние компоненты отсекаются.
  4. Бюджет заполняется по уровням: компонент -> SQL, который он использует -> его тесты ->
     импорты на шаг -> документация -> остальное по оценке.

Отсечение соседних компонентов — самое опасное правило: если задача действительно затрагивает два
компонента, оно выкинет половину нужного. Поэтому оно включается только при доказанной концентрации
якорей (см. _component_root), у него есть запасной выход через импорты, и оно объясняет себя в лог.

Содержимое недоверенных файлов (repo/trust.py) не читается и в files не попадает — наружу уходят
только пути в untrusted_paths и цели инъекций в injection_targets.

Своего класса ошибки у модуля нет: структурные проблемы приходят из SnapshotError и ProfileError,
а сам отбор — эвристика и деградирует до пустых списков.
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from harness.contracts import ContextFile, RepoContext, RunProfile
from harness.repo.profile import detect_run_profile
from harness.repo.python_index import find_imports, index_python
from harness.repo.snapshot import compute_snapshot_sha256, list_regular_files
from harness.repo.sql_index import index_sql
from harness.repo.trust import find_injection_targets, find_untrusted_with_reasons

LOGGER = logging.getLogger(__name__)

MAX_FILE_BYTES = 128 * 1024
ANCHOR_COUNT = 5
ANCHOR_QUORUM = 4          # сколько якорей из ANCHOR_COUNT должны лежать под одним корнем
PATH_WEIGHT = 3.0          # совпадение в пути весомее совпадения в тексте
MIN_KEYWORD_LENGTH = 4
KEYWORDS_IN_REASON = 3
MIN_BARE_SQL_NAME = 6      # короткое имя без схемы ('line') слишком часто встречается случайно

DOC_SUFFIXES: frozenset[str] = frozenset({".md", ".rst", ".txt"})

TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]+|[А-Яа-яЁё]{3,}")
CAMEL = re.compile(r"([a-z0-9])([A-Z])")

EN_SUFFIXES: tuple[str, ...] = ("ements", "ement", "ations", "ation", "ings", "ing", "ies", "ied",
                                "ed", "es", "s")
RU_SUFFIXES: tuple[str, ...] = ("ования", "ации", "ация", "ого", "ому", "ами", "ах", "ам", "ов",
                                "ии", "ия", "ие", "ой", "ый", "ые", "ых", "ы", "и", "а", "е", "у",
                                "ю", "я", "ь")

# Слова самого задания: они описывают, что сделать, а не про что репозиторий.
STOP_STEMS: frozenset[str] = frozenset({
    "подготов", "исправ", "устран", "репозитор", "кейс", "задач", "должн", "должен", "нужн",
    "сдела", "сохран", "реальн", "текущ", "котор", "также", "этот", "прочее",
    "should", "must", "please", "repositor", "task", "case", "this", "that", "with", "from",
    "into", "make", "need", "keep", "ensure",
})


@dataclass
class _File:
    path: str
    text: str
    score: float = 0.0
    keywords: list[str] = field(default_factory=list)

    @property
    def rank(self) -> tuple[float, str]:
        return (-self.score, self.path)


def build_context(repo: Path, brief: str, *, max_files: int = 20) -> RepoContext:
    all_paths = list_regular_files(repo)
    untrusted = [item.path for item in find_untrusted_with_reasons(repo)]
    profile = detect_run_profile(repo)
    targets = find_injection_targets(repo)

    files = _readable(repo, all_paths, frozenset(untrusted))
    _score(files, _keywords(brief))

    root = _component_root(_anchors(files, profile), len(all_paths))
    excluded = _excluded(root, files) if root is not None else frozenset()
    selection, tests = _select(repo, files, profile, root, excluded, max_files)

    chosen = [item.path for item, _ in selection]
    return RepoContext(
        snapshot_sha256=compute_snapshot_sha256(repo),
        brief=brief,
        files=[ContextFile(path=item.path, content=item.text, reason=reason)
               for item, reason in selection],
        python_symbols=index_python(repo, [path for path in chosen if path.endswith(".py")]),
        sql_objects=index_sql(repo, [path for path in chosen if path.endswith(".sql")]),
        existing_tests=sorted(tests),
        run_profile=profile,
        untrusted_paths=untrusted,
        injection_targets=targets,
        total_files_in_repo=len(all_paths),
    )


# ---------------------------------------------------------------------------
# Чтение и оценка
# ---------------------------------------------------------------------------

def _readable(repo: Path, paths: list[str], untrusted: frozenset[str]) -> list[_File]:
    """Доверенные текстовые файлы. Недоверенные не читаются вообще, бинарные и огромные не нужны."""
    files: list[_File] = []
    for relative_path in paths:
        if relative_path in untrusted:
            continue
        text = _read(repo / relative_path)
        if text is not None:
            files.append(_File(relative_path, text))
    return files


def _read(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\0" in raw:
        return None
    return raw.decode("utf-8", errors="replace")


def _stem(word: str) -> str:
    word = word.lower()
    for suffix in EN_SUFFIXES + RU_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= MIN_KEYWORD_LENGTH:
            return word[:-len(suffix)]
    return word


def _tokens(text: str) -> set[str]:
    return {_stem(token) for token in TOKEN.findall(CAMEL.sub(r"\1 \2", text))}


def _keywords(brief: str) -> set[str]:
    return {token for token in _tokens(brief)
            if len(token) >= MIN_KEYWORD_LENGTH and token not in STOP_STEMS}


def _score(files: list[_File], keywords: set[str]) -> None:
    """Оценка = сумма весов совпавших слов; вес слова — ln((N+1)/(df+1)), совпадение в пути втрое."""
    in_path = {item.path: _tokens(item.path) & keywords for item in files}
    in_text = {item.path: _tokens(item.text) & keywords for item in files}
    document_frequency: Counter[str] = Counter()
    for item in files:
        document_frequency.update(in_path[item.path] | in_text[item.path])
    total = len(files)
    weight = {word: math.log((total + 1) / (document_frequency[word] + 1)) for word in keywords}

    for item in files:
        matched: dict[str, float] = {}
        for word in in_path[item.path]:
            matched[word] = matched.get(word, 0.0) + PATH_WEIGHT * weight[word]
        for word in in_text[item.path]:
            matched[word] = matched.get(word, 0.0) + weight[word]
        item.score = sum(matched.values())
        item.keywords = sorted(matched, key=lambda word: (-matched[word], word))


# ---------------------------------------------------------------------------
# Корень компонента и отсечение соседей
# ---------------------------------------------------------------------------

def _anchors(files: list[_File], profile: RunProfile) -> list[str]:
    """Самые сильные файлы с кодом. Тесты в якоря не идут: они лежат в своём дереве."""
    code = [item for item in sorted(files, key=lambda item: item.rank)
            if item.path.endswith(".py") and item.score > 0 and not _is_test(item.path, profile)]
    return [item.path for item in code[:ANCHOR_COUNT]]


def _component_root(anchors: list[str], total_files: int) -> str | None:
    """Самый глубокий каталог, под которым лежит не меньше ANCHOR_QUORUM якорей.

    Предохранители: якорей должно хватать на кворум, и корень не должен занимать половину
    репозитория — иначе «корнем» окажется общий слой, и отсечение выбросит соседние подсистемы.
    """
    if len(anchors) < ANCHOR_QUORUM:
        LOGGER.info("отсечение соседних компонентов выключено: якорей всего %d", len(anchors))
        return None
    counts: Counter[str] = Counter()
    for anchor in anchors:
        parts = PurePosixPath(anchor).parts
        for depth in range(1, len(parts)):
            counts["/".join(parts[:depth])] += 1
    quorum = [directory for directory, found in counts.items() if found >= ANCHOR_QUORUM]
    if not quorum:
        LOGGER.info("отсечение выключено: якоря разошлись по компонентам (%s)", ", ".join(anchors))
        return None
    root = max(quorum, key=lambda directory: (directory.count("/"), directory))
    return root


def _excluded(root: str, files: list[_File]) -> frozenset[str]:
    """Файлы соседних компонентов.

    Каталог считается разложенным по компонентам, если имя хотя бы одной его подпапки содержит имя
    корня компонента. Тогда остальные его подпапки — соседние компоненты, и в контекст не идут.
    """
    name = root.rpartition("/")[2]
    children: dict[tuple[str, ...], set[str]] = {}
    for item in files:
        parts = tuple(item.path.split("/"))
        for depth in range(len(parts) - 1):
            children.setdefault(parts[:depth], set()).add(parts[depth])

    excluded: set[str] = set()
    cut: set[str] = set()
    for item in files:
        parts = tuple(item.path.split("/"))
        for depth in range(len(parts) - 1):
            siblings = children[parts[:depth]]
            if any(name in sibling for sibling in siblings) and name not in parts[depth]:
                excluded.add(item.path)
                cut.add("/".join(parts[:depth + 1]))
                break
    LOGGER.info("корень компонента %s; отсечены соседние каталоги: %s (%d файлов)",
                root, ", ".join(sorted(cut)) or "нет", len(excluded))
    return frozenset(excluded)


# ---------------------------------------------------------------------------
# Отбор по уровням
# ---------------------------------------------------------------------------

def _select(repo: Path, files: list[_File], profile: RunProfile, root: str | None,
            excluded: frozenset[str], max_files: int) -> tuple[list[tuple[_File, str]], list[str]]:
    by_path = {item.path: item for item in files}
    open_files = [item for item in sorted(files, key=lambda item: item.rank)
                  if item.path not in excluded]

    component = [item for item in open_files if root is not None and _under(item.path, root)]
    sql_map = _sql_objects(repo, [item.path for item in open_files if item.path.endswith(".sql")])

    defines = _referenced(component, sql_map)
    tests = _component_tests(repo, open_files, profile, root, sql_map, defines)
    # Ссылка из кода компонента объясняет файл лучше ссылки из теста, поэтому не перезаписывается.
    for path, qualname in _referenced(tests, sql_map).items():
        defines.setdefault(path, qualname)

    importers = _imports(repo, [*component, *tests], [*profile.pytest_pythonpath], by_path)
    imported = sorted((by_path[path] for path in importers), key=lambda item: item.rank)

    # Бюджет расходуется по уровням, а не по оценке: если он меньше компонента, побеждает компонент,
    # и файл с дефектом не вытесняется хорошо совпавшей документацией.
    taken: dict[str, str] = {}

    def take(items: list[_File], reason: Callable[[_File], str]) -> None:
        for item in items:
            if len(taken) >= max_files:
                return
            taken.setdefault(item.path, reason(item))

    take(component, lambda item: f"component of {root}")
    take(sorted((by_path[path] for path in defines), key=lambda item: item.rank),
         lambda item: f"defines {defines[item.path]}")
    take(tests, lambda item: f"existing test of {root}")
    take(imported, lambda item: f"imported by {importers[item.path]}")
    take([item for item in open_files
          if item.score > 0 and PurePosixPath(item.path).suffix in DOC_SUFFIXES],
         lambda item: "project documentation")
    take([item for item in open_files if item.score > 0], lambda item: "brief keyword")

    chosen = sorted((by_path[path] for path in taken), key=lambda item: item.rank)
    selection = [(item, _reason(taken[item.path], item)) for item in chosen]
    return selection, [item.path for item in tests]


def _reason(base: str, item: _File) -> str:
    keywords = ", ".join(item.keywords[:KEYWORDS_IN_REASON])
    if base == "brief keyword":
        return f"brief keyword: {keywords}"
    return f"{base}; brief keyword: {keywords}" if keywords else base


def _under(path: str, root: str) -> bool:
    return path.startswith(f"{root}/")


def _is_test(path: str, profile: RunProfile) -> bool:
    name = PurePosixPath(path).name
    if name.startswith("test_") or name.endswith(("_test.py", "_test.sql")):
        return True
    return any(path.startswith(f'{testpath.rstrip("/")}/') for testpath in profile.pytest_testpaths)


def _sql_objects(repo: Path, paths: list[str]) -> dict[str, str]:
    """Полное имя SQL-объекта -> файл, который его объявляет."""
    found: dict[str, str] = {}
    for obj in index_sql(repo, paths):
        if "." in obj.qualname or len(obj.qualname) >= MIN_BARE_SQL_NAME:
            found.setdefault(obj.qualname, obj.path)
    return found


def _referenced(items: list[_File], sql_map: dict[str, str]) -> dict[str, str]:
    """Файл -> самое длинное имя объекта, из-за которого он понадобился."""
    found: dict[str, str] = {}
    for qualname in sorted(sql_map, key=lambda name: (-len(name), name)):
        path = sql_map[qualname]
        if path in found:
            continue
        if any(qualname in item.text for item in items):
            found[path] = qualname
    return found


def _component_tests(repo: Path, open_files: list[_File], profile: RunProfile, root: str | None,
                     sql_map: dict[str, str], defines: dict[str, str]) -> list[_File]:
    """Тесты, которые относятся к компоненту: импортируют его модуль или трогают его SQL-объекты."""
    if root is None:
        return []
    names = [name for name, path in sql_map.items() if path in defines]
    tests: list[_File] = []
    for item in open_files:
        if not _is_test(item.path, profile):
            continue
        imports = find_imports(repo, item.path, [*profile.pytest_pythonpath])
        if any(_under(path, root) for path in imports):
            tests.append(item)
        elif any(name in item.text for name in names):
            tests.append(item)
    return tests


def _imports(repo: Path, items: list[_File], roots: list[str],
             by_path: dict[str, _File]) -> dict[str, str]:
    """Импорты на один шаг: путь -> кто его импортирует.

    Это запасной выход и для общего кода вне компонента, и для соседа, отсечённого по имени папки:
    если компонент действительно на него опирается, файл возвращается в контекст.
    """
    known = {item.path for item in items}
    found: dict[str, str] = {}
    for item in sorted(items, key=lambda item: item.path):
        if not item.path.endswith(".py"):
            continue
        for path in find_imports(repo, item.path, roots):
            if path not in known and path in by_path:
                found.setdefault(path, item.path)
    return found
