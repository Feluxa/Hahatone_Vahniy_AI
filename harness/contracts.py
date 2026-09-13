"""Общие структуры данных харнесса.

Это единственный файл, через который модули разных участников обмениваются данными.
Правила изменения (см. docs/WORKFLOW.md):
  * добавлять новые поля можно, но только со значением по умолчанию;
  * переименовывать, удалять и менять тип существующих полей — только по договорённости в чате;
  * никакой логики, кроме простых свойств и сериализации.

Все структуры сериализуются в JSON через harness.serde (to_dict / from_dict),
поэтому поля должны быть простыми типами, Enum, Path, list/dict или другими dataclass-ами.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

PROTOCOL_VERSION = "1.0"
TASK_SCHEMA_VERSION = "1.1"


# ---------------------------------------------------------------------------
# Вход (PROTOCOL.md, раздел 1). Владелец разбора: protocol/input.py
# ---------------------------------------------------------------------------

class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class Language(str, Enum):
    """Язык задания (instruction.md), а не язык программирования."""
    RU = "ru"
    EN = "en"


@dataclass(frozen=True)
class Author:
    name: str
    email: str


@dataclass(frozen=True)
class Limits:
    agent_timeout_sec: int
    verifier_timeout_sec: int
    build_timeout_sec: int
    cpus: float
    memory_mb: int
    storage_mb: int


@dataclass(frozen=True)
class CaseInput:
    """Провалидированный вход. Пути уже абсолютные (разрешены от папки входного JSON)."""
    protocol_version: str
    repository: Path
    brief: str
    output_dir: Path
    case_id: str
    difficulty: Difficulty
    language: Language
    source: str
    team: str
    author: Author
    limits: Limits
    seed: int
    input_path: Path | None = None


# ---------------------------------------------------------------------------
# Контекст репозитория. Владелец: участник №1 (repo/*)
# ---------------------------------------------------------------------------

class Trust(str, Enum):
    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"  # импортированные тикеты, фиды, всё, что может содержать инъекции


@dataclass(frozen=True)
class ContextFile:
    path: str             # относительный POSIX-путь внутри репозитория
    content: str
    reason: str           # почему файл попал в контекст: "brief keyword: settlement", "import of ..."
    trust: Trust = Trust.TRUSTED


@dataclass(frozen=True)
class PythonSymbol:
    path: str
    kind: str             # "class" | "function" | "method"
    qualname: str         # "NettingPolicy.build"
    signature: str        # "(self, tenant_id: str, ...) -> SettlementModel"
    line: int
    docstring: str | None = None


@dataclass(frozen=True)
class SqlObject:
    path: str
    kind: str             # "schema" | "table" | "function" | "view" | "index" | "constraint"
    qualname: str         # "bank_settlement.refresh_daily_settlement"
    signature: str | None = None  # аргументы функции или список колонок
    line: int | None = None


@dataclass(frozen=True)
class RunProfile:
    """Как проект устанавливается и тестируется. Нужен №3 для Dockerfile и №2 для промптов."""
    python_version: str                         # "3.11"
    requirements_file: str | None               # "requirements.lock"
    pytest_pythonpath: list[str] = field(default_factory=list)   # ["backend/src"]
    pytest_testpaths: list[str] = field(default_factory=list)    # ["tests"]
    needs_postgres: bool = False
    postgres_major: int | None = None           # 16
    migration_command: list[str] | None = None  # ["python", "-m", "alembic", "upgrade", "head"]
    seed_sql_files: list[str] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)  # имена переменных и назначение, без секретов


@dataclass(frozen=True)
class RepoContext:
    snapshot_sha256: str
    brief: str
    files: list[ContextFile]
    python_symbols: list[PythonSymbol]
    sql_objects: list[SqlObject]
    existing_tests: list[str]                   # пути существующих тестов, относящихся к брифу
    run_profile: RunProfile
    untrusted_paths: list[str] = field(default_factory=list)
    # Пути, которые недоверенные тексты просят изменить или перезаписать. Кандидаты на anti_cheat
    # «файл не изменён», а не готовый список: сначала отфильтровать по спецификации кейса.
    injection_targets: list[str] = field(default_factory=list)
    total_files_in_repo: int = 0


# ---------------------------------------------------------------------------
# Черновик кейса. Владелец генерации: участник №2 (llm/*)
# Эталонный черновик руками: участник №3 (golden/)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CaseSpec:
    goal: str
    behavior: list[str]
    invariants: list[str]          # всё, что обязано сохраниться; каждое должно попасть в instruction.md
    edge_cases: list[str]
    defect_hypothesis: str         # только для внутреннего использования, в instruction.md не попадает
    bank_domain: str               # для task.toml [metadata].bank_domain
    description: str               # для task.toml [task].description, одна строка


@dataclass(frozen=True)
class TestLists:
    """Полные pytest ID, например 'tests/test_settlement.py::test_refund_reduces_net'."""
    __test__ = False  # чтобы pytest не пытался собрать класс

    fail_to_pass: list[str]
    pass_to_pass: list[str]
    anti_cheat: list[str]

    def all_ids(self) -> list[str]:
        return [*self.fail_to_pass, *self.pass_to_pass, *self.anti_cheat]

    def duplicates(self) -> list[str]:
        seen: set[str] = set()
        dups: list[str] = []
        for test_id in self.all_ids():
            if test_id in seen and test_id not in dups:
                dups.append(test_id)
            seen.add(test_id)
        return dups


@dataclass(frozen=True)
class CaseDraft:
    spec: CaseSpec
    instruction_md: str
    test_files: dict[str, str]      # путь внутри task/tests/ -> содержимое (без шаблонных test.sh и conftest.py)
    lists: TestLists
    solution_files: dict[str, str]  # путь внутри task/solution/ -> содержимое, обязательно "solve.sh"
    # Файлы репозитория, неизменность которых проверяет anti_cheat: относительные POSIX-пути
    # внутри исходника. Эталон для побайтного сравнения кладёт сам харнесс
    # (write_task_folder -> tests/expected/<путь>.expected), модель только называет путь:
    # содержимое, переписанное моделью, побайтно уже не совпадёт.
    protected_files: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Прогоны и вердикт. Владелец: участник №3 (verify/*)
# ---------------------------------------------------------------------------

class TestOutcome(str, Enum):
    __test__ = False

    PASSED = "passed"
    FAILED = "failed"     # упал assert или исключение в теле теста
    ERROR = "error"       # ошибка фикстуры, импорта, окружения
    SKIPPED = "skipped"   # включая xfail
    MISSING = "missing"   # ожидался по task.toml, но не собран / не запустился


@dataclass(frozen=True)
class TestReport:
    __test__ = False

    outcome: TestOutcome
    message: str | None = None      # первая строка сообщения failure/error
    exception_type: str | None = None  # "AssertionError", "ImportError", ...

    @property
    def failed_by_assertion(self) -> bool:
        return self.outcome is TestOutcome.FAILED and self.exception_type == "AssertionError"


class RunKind(str, Enum):
    BUILD = "build"
    BASE = "base"
    ORACLE = "oracle"
    MUTANT = "mutant"


class RunScope(str, Enum):
    FULL = "full"                   # tests/test.sh целиком
    FAIL_TO_PASS = "fail_to_pass"
    PASS_TO_PASS = "pass_to_pass"
    ANTI_CHEAT = "anti_cheat"
    COLLECT = "collect"             # pytest --collect-only


@dataclass(frozen=True)
class RunResult:
    """Один прогон. Эти поля напрямую попадают в evidence/summary.json."""
    name: str                       # "base/full", "oracle/pass_to_pass", "repeat/base/full", "mutant/hunk-2"
    kind: RunKind
    scope: RunScope
    executed: bool                  # False = не выполнялся; такой прогон никогда не считается успешным
    commands: list[str]
    image_digest: str | None
    duration_sec: float | None
    exit_code: int | None
    reward: int | None              # 0/1 из /logs/verifier/reward.txt; None, если не записан
    report_path: str | None         # относительно evidence/, например "base/full/verifier/tests.xml"
    log_dir: str | None             # относительно evidence/
    tests: dict[str, TestReport] = field(default_factory=dict)
    repeat_of: str | None = None    # для повторов: имя исходного прогона
    note: str | None = None         # таймаут, OOM, причина невыполнения


class MutantSource(str, Enum):
    HUNK_REVERT = "hunk_revert"
    LLM = "llm"
    ALTERNATIVE_SOLUTION = "alternative_solution"


@dataclass(frozen=True)
class Mutant:
    name: str
    source: MutantSource
    description: str
    patch: str                      # unified diff относительно состояния после solve.sh (корень = /app/repo)
    # Мутант-замена: харнесс сам находит anchor в file_path и меняет на replacement, как это
    # делает solve.sh. Якорь обязан встречаться ровно один раз, иначе мутант невалиден.
    # Так их задаёт LLM: unified diff от модели стабильно не накладывался (patch не находил
    # контекст). Для hunk_revert поля пустые, там применяется patch.
    file_path: str = ""             # путь относительно /app/repo
    anchor: str = ""                # заменяемый текст
    replacement: str = ""           # чем заменяется
    expected_reward: int = 0        # 0 для мутантов-ошибок, 1 для альтернативных корректных решений

    @property
    def is_replacement(self) -> bool:
        return bool(self.file_path and self.anchor)


class ProblemCategory(str, Enum):
    INPUT_INVALID = "input_invalid"
    SOURCE_MODIFIED = "source_modified"
    BUILD_FAILED = "build_failed"
    LIST_MISMATCH = "list_mismatch"            # собранные тесты != объединению списков, дубли
    FORBIDDEN_MARKERS = "forbidden_markers"    # skip / xfail
    BASE_F2P_PASSED = "base_f2p_passed"        # дефект не воспроизводится
    BASE_NOT_ASSERTION = "base_not_assertion"  # f2p падает на импорте/окружении, а не на assert
    BASE_GUARD_FAILED = "base_guard_failed"    # p2p или anti_cheat падают на исходном коде
    ORACLE_FAILED = "oracle_failed"
    REWARD_WRONG = "reward_wrong"
    NOT_REPRODUCIBLE = "not_reproducible"
    MUTANT_SURVIVED = "mutant_survived"
    ALTERNATIVE_SOLUTION_FAILED = "alternative_solution_failed"  # PROTOCOL §5.7: тесты отвергли корректную альтернативу
    INSTRUCTION_LEAK = "instruction_leak"      # имена тестов, пути tests/ solution/, куски решения
    SOLUTION_TOUCHES_TESTS = "solution_touches_tests"
    TASK_DIR_DIRTY = "task_dir_dirty"          # логи, кэши, .git, .venv в task/
    TIMEOUT = "timeout"
    INTERNAL = "internal"
    # Тест падает одинаково до и после решения не по assert: невалиден сам тест, не продукт.
    TEST_INVALID = "test_invalid"



class RepairTarget(str, Enum):
    TESTS = "tests"
    SOLUTION = "solution"
    INSTRUCTION = "instruction"
    ENVIRONMENT = "environment"
    NONE = "none"                   # чинить нечего или нельзя (например, исходник изменён)


@dataclass(frozen=True)
class Problem:
    category: ProblemCategory
    target: RepairTarget
    details: str                    # короткий текст, пригодный для промпта ремонта
    test_ids: list[str] = field(default_factory=list)
    run_names: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Verdict:
    ok: bool
    problems: list[Problem] = field(default_factory=list)
    runs: list[str] = field(default_factory=list)   # имена прогонов, на которых основан вердикт
    # То, что верификация изменила или заметила, но провалом не считает: например
    # переклассификация теста между списками по фактическим исходам. Уезжает в
    # CaseResult.limitations и на ok не влияет.
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# LLM usage. Владелец: участник №2 (evidence/usage.py)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LlmCall:
    model: str
    duration_sec: float
    input_tokens: int | None
    output_tokens: int | None
    purpose: str | None = None      # "spec", "tests", "solution", "mutants", "repair:tests" — доп. поле


@dataclass
class UsageLog:
    calls: list[LlmCall] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Результат (PROTOCOL.md, раздел 2). Владелец: protocol/output.py
# ---------------------------------------------------------------------------

class Status(str, Enum):
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True)
class CaseResult:
    protocol_version: str
    case_id: str
    status: Status
    task_path: str | None
    evidence_path: str | None
    limitations: list[str]
    input_snapshot_sha256: str | None
