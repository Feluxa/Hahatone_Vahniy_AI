# LLM Test-Case Harness

Харнесс получает репозиторий и бриф, с помощью LLM генерирует тест-кейс для AI-разработчика (задание, Docker-окружение, скрытые тесты, эталонное решение) и сам доказывает, что кейс корректен. Формат входа и результата — `PROTOCOL.md` организаторов.

Подробный план: `docs/PLAN.docx`. Правила совместной работы: `docs/WORKFLOW.md`.

## Быстрый старт для разработки

```sh
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

## Запуск

```sh
python -m harness run materials/hackathon-participants/inputs/settlement.json
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
| `harness/pipeline.py`, `harness/cli.py`, `harness/verify/static_checks.py` | оркестрация, CLI, статические проверки | №4 |
| `fixtures/` | примеры данных для работы без чужого кода | каждый — свои |

## Главные точки стыковки

- №1 → №2: `repo.context.build_context(repo, brief) -> RepoContext` и `fixtures/repo_context.settlement.json`.
- №3 → №2, №4: `verify.api.verify_case(task_dir, evidence_dir, limits) -> (list[RunResult], Verdict)`.
- №1 → №3: `build.manifest.read_test_lists(task.toml) -> TestLists`; до готовности — читать `tomllib` напрямую.
- №2 → №4: `CaseDraft`, `UsageLog`; №1 превращает `CaseDraft` в папку `task/`.

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
| repo.context (№1) | готово | `build_context(repo, brief, max_files=20)`; на meridian — 20 файлов, без `components/lending` и `payments`; `fixtures/repo_context.settlement.json` (перегенерация — `.venv/Scripts/python.exe -m tests.repo.regen_settlement_fixture`) |
| manifest, task_folder (№1) | заглушки | |
| environment, verify, summary, golden (№3) | готово | покрыто `tests/verify/` и `tests/build/` |
| llm.client, llm.parsing, evidence.usage (№2) | готово | GigaChat-3-Ultra, парсинг JSON/файлов/патчей, `.env.example`, `write_usage`; `tests/llm/`, `tests/evidence/test_usage.py` |
| llm.spec (№2) | готово | `write_spec`, `write_instruction`, защита от утечек и инъекций; `tests/llm/test_spec_writer.py` |
| llm.test (№2) | готово | `write_tests`, AST-парсинг функций, канонизация ID, три списка без дублей; `tests/llm/test_test_writer.py` |
| llm.solution (№2) | готово | `write_solution`, безопасные замены с `count(anchor)==1`, валидация запретов; `tests/llm/test_solution_writer.py` |
| llm.mutants (№2) | готово | `write_mutants`, генерация и нормализация unified diff; `tests/llm/test_mutant_writer.py` |
| llm.repair (№2) | готово | `repair` (точечный ремонт по target), `create_case_draft` (сквозной сборщик); `tests/llm/test_repair.py` |
| pipeline, cli, static_checks (№4) | заглушки | |

### Эталонный хэш снимка

Исходный репозиторий `materials/hackathon-participants/meridian`: 187 обычных файлов, включая скрытый `.gitignore`.

```text
f63dfc6392b934d50c961f11250cc576d1160c27f4beb13628b5a720ffccea50
```

Это значение попадает в `result.json` как `input_snapshot_sha256` и сверяется в конце прогона. Проверить вручную:

```sh
python -c "from pathlib import Path; from harness.repo.snapshot import compute_snapshot_sha256; print(compute_snapshot_sha256(Path('materials/hackathon-participants/meridian')))"
```

Если хэш отличается — содержимое `materials/` изменено, а менять его нельзя: от побайтного совпадения зависят anti_cheat-проверки.