# LLM Test-Case Harness

Харнесс получает репозиторий и бриф, с помощью LLM генерирует тест-кейс для AI-разработчика (задание, Docker-окружение, скрытые тесты, эталонное решение) и сам доказывает, что кейс корректен. Формат входа и результата — `PROTOCOL.md` организаторов.

Подробный план: `docs/PLAN.docx`. Правила совместной работы: `docs/WORKFLOW.md`.

## Быстрый старт для разработки

```sh
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Материалы организаторов распакуйте локально в `materials/` (папка в `.gitignore`):

```text
materials/hackathon-participants/
├── PROTOCOL.md
├── example-case/
├── inputs/settlement.json
└── meridian/
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
| repo, protocol, manifest, task_folder (№1) | заглушки | |
| environment, verify, summary, golden (№3) | заглушки | |
| llm, usage (№2) | заглушки | |
| pipeline, cli, static_checks (№4) | заглушки | |
