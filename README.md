# LLM Test-Case Harness

Харнесс получает репозиторий и бриф, с помощью LLM генерирует тест-кейс для AI-разработчика (задание, Docker-окружение, скрытые тесты, эталонное решение) и сам доказывает, что кейс корректен. Формат входа и результата — `PROTOCOL.md` организаторов.

Подробный план: `docs/PLAN.docx`. Правила совместной работы: `docs/WORKFLOW.md`.

## Быстрый старт для разработки

Разработка идёт на Windows, поэтому команды ниже — для PowerShell. Минимальная версия — Python 3.11 (в текущем `.venv` — 3.13).

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -m "not docker and not llm"
.venv\Scripts\python.exe -m ruff check harness/ tests/
```

Последние две команды — обязательный минимум перед завершением шага. Сейчас весь набор проходит без Docker и без обращений к LLM: 469 passed, 5 skipped (пропуски — тесты симлинков и POSIX-прав: им нужны права на создание симлинков или не-Windows).

Рантайм зависит только от стандартной библиотеки и `gigachat` (`requirements.txt`); `requirements-dev.txt` добавляет `pytest` и `ruff`. Для работы с LLM скопируйте `.env.example` в `.env` и заполните доступы к GigaChat.

## Запуск

```powershell
.venv\Scripts\python.exe -m harness run materials/hackathon-participants/inputs/settlement.json
```

Пока пайплайн не реализован, команда завершается с кодом 1. Коды выхода: 0 — `ready`, 1 — `failed`, 2 — некорректный вход.

## Структура и владельцы

| Путь | Что | Владелец |
|---|---|---|
| `harness/contracts.py`, `harness/serde.py` | общие структуры данных и их JSON | все, изменения через чат |
| `harness/repo/` | snapshot, чистая копия, контекст для LLM, индексы Python/SQL, недоверенные файлы, профиль запуска | №1 |
| `harness/protocol/` | вход (`input.py`) и `result.json` (`output.py`) | №1 |
| `harness/build/manifest.py`, `harness/build/task_folder.py` | `task.toml` и сборка папки `task/` | №1 |
| `harness/build/environment.py`, `harness/build/templates/` | Dockerfile, conftest с PostgreSQL, test.sh | №3 |
| `harness/verify/` (кроме `static_checks.py`) | Docker, матрица прогонов, junit, мутанты, вердикт, `api.verify_case` | №3 |
| `harness/evidence/summary.py` | `evidence/summary.json` | №3 |
| `golden/settlement-001/` | эталонный кейс, написанный руками | №3 |
| `harness/llm/`, `harness/evidence/usage.py` | промпты, генерация, ремонт, `llm_usage.json` | №2 |
| `harness/pipeline.py`, `harness/cli.py`, `harness/__main__.py`, `harness/verify/static_checks.py` | оркестрация, CLI, статические проверки | №4 |
| `fixtures/` | примеры данных для работы без чужого кода | каждый — свои |

## Главные точки стыковки

- №1 → №2: `repo.context.build_context(repo, brief, max_files=20) -> RepoContext` и `fixtures/repo_context.settlement.json`.
- №3 → №2, №4: `verify.api.verify_case(task_dir, evidence_dir, limits, options=None) -> (list[RunResult], Verdict)`, настройки — `verify.api.VerifyOptions`.
- №1 → №3: `build.manifest.read_test_lists(task.toml) -> TestLists`.
- №2 → №4: `llm.repair.create_case_draft(client, context, language) -> CaseDraft` и `llm.repair.repair(client, context, draft, verdict, log_excerpts) -> CaseDraft`; `evidence.usage.write_usage(evidence_dir, UsageLog)`. №1 превращает `CaseDraft` в папку `task/`.

## Статус модулей

Обновляйте в конце каждой сессии: что работает, как запустить, известные проблемы.

| Модуль | Статус | Заметки |
|---|---|---|
| contracts, serde | готово | покрыто `tests/test_contracts.py` |
| repo.snapshot (№1) | готово | `compute_snapshot_sha256`, `list_regular_files`; `tests/repo/test_snapshot.py`; эталонный хэш meridian — ниже |
| repo.workspace (№1) | готово | `copy_clean(src, dst) -> список пропущенного`; `tests/repo/test_workspace.py` |
| protocol.input, protocol.output (№1) | готово | `load_input` собирает все проблемы входа сразу; `write_result` пишет `result.json` атомарно; `tests/protocol/` |
| repo.trust (№1) | готово | `find_untrusted`, `find_untrusted_with_reasons`, `find_injection_targets`; признаки общие, код недоверенным не становится; `tests/repo/test_trust.py` |
| repo.profile (№1) | готово | `detect_run_profile(repo) -> RunProfile`; деградирует до дефолтов, `ProfileError` только на структурных проблемах; `tests/repo/test_profile.py` |
| repo.python_index, repo.sql_index (№1) | готово | `index_python` (+`find_imports`), `index_sql`; `tests/repo/test_python_index.py`, `test_sql_index.py` |
| repo.context (№1) | готово | `build_context(repo, brief, max_files=20)`; на meridian — 20 файлов, без `components/lending` и `payments`; `fixtures/repo_context.settlement.json` (перегенерация — `.venv\Scripts\python.exe -m tests.repo.regen_settlement_fixture`) |
| build.manifest (№1) | готово | `render_task_toml(case, spec, lists)` повторяет `example-case/task.toml` дословно, `read_test_lists(task.toml)` — обратно; списки проверяются на запись и на чтение, `ManifestError.problems`; `tests/build/test_manifest.py` |
| build.task_folder (№1) | готово | `write_task_folder(task_dir, case, draft, profile, workspace_repo)`; структура по PROTOCOL §3, всё своё пишется с LF, `environment/repo/` — `copy_clean`; на черновике из `golden/settlement-001` даёт тот же набор файлов; `tests/build/test_task_folder.py` |
| build.environment (№3) | готово | `render_dockerfile`, `render_conftest`, `render_test_sh`, `write_environment` по шаблонам из `harness/build/templates/`; `tests/build/test_environment.py` |
| verify (кроме `static_checks`), evidence.summary, golden (№3) | готово | `verify.api.verify_case` поверх `docker.py`, `runs.py`, `junit.py`, `mutation.py`, `verdict.py`; `VerifyOptions(repeat, run_mutants, extra_mutants, keep_image)`; покрыто `tests/verify/` и `tests/evidence/test_summary.py` |
| llm.client, llm.parsing, evidence.usage (№2) | готово | GigaChat-3-Ultra, `load_env`, `LlmClient`, `LlmError`, парсинг JSON/файлов/патчей, `.env.example`, `write_usage`; `tests/llm/`, `tests/evidence/test_usage.py` |
| llm.spec_writer (№2) | готово | `write_spec`, `write_instruction`, защита от утечек и инъекций; `tests/llm/test_spec_writer.py` |
| llm.test_writer (№2) | готово | `write_tests`, AST-парсинг функций, канонизация ID, три списка без дублей; `tests/llm/test_test_writer.py` |
| llm.solution_writer (№2) | готово | `write_solution`, безопасные замены с `count(anchor)==1`, валидация запретов; `tests/llm/test_solution_writer.py` |
| llm.mutant_writer (№2) | готово | `write_mutants`, генерация и нормализация unified diff; `tests/llm/test_mutant_writer.py` |
| llm.repair (№2) | готово | `repair` (точечный ремонт по target), `create_case_draft` (сквозной сборщик); `tests/llm/test_repair.py` |
| verify.static_checks (№4) | заглушка | `check_task_folder(task_dir, lists) -> list[Problem]` поднимает `NotImplementedError`; следующий шаг |
| cli (№4) | заглушка | `python -m harness run <input>` разбирает аргументы и выходит с кодом 1 |
| pipeline (№4) | заглушка | `run(case) -> CaseResult` поднимает `NotImplementedError`; `MAX_REPAIR_ITERATIONS = 3` |

Порядок работы №4: `static_checks.py` → `cli.py` → `pipeline.py`, с остановкой на коммит после каждого.

### Эталонный хэш снимка

Исходный репозиторий `materials/hackathon-participants/meridian`: 187 обычных файлов, включая скрытый `.gitignore`.

```text
f63dfc6392b934d50c961f11250cc576d1160c27f4beb13628b5a720ffccea50
```

Это значение попадает в `result.json` как `input_snapshot_sha256` и сверяется в конце прогона. Проверить вручную:

```powershell
.venv\Scripts\python.exe -c "from pathlib import Path; from harness.repo.snapshot import compute_snapshot_sha256; print(compute_snapshot_sha256(Path('materials/hackathon-participants/meridian')))"
```

Если хэш отличается — содержимое `materials/` изменено, а менять его нельзя: от побайтного совпадения зависят anti_cheat-проверки.
