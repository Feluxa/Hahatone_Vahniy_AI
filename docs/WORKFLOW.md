# Как работаем в одном репозитории

## График

| Когда | Кто | Итог к концу сессии |
|---|---|---|
| Сегодня | №1 | snapshot, workspace, trust, profile, context, input/output, manifest, task_folder; `fixtures/repo_context.settlement.json` |
| Сегодня | №3 | эталон `golden/settlement-001`; Dockerfile с PG16, conftest, test.sh; docker runner, junit, `verify_case` для base/oracle; `fixtures/runs.golden.json` |
| Завтра утром | №2 | клиент с usage, spec/instruction, tests, solution; к обеду — сквозной скрипт context → draft → task/ → verify_case |
| Завтра вечером | №4 | pipeline с repair loop, CLI, static_checks, README, финальный прогон на `inputs/settlement.json` |

Минимум к утру завтра, без которого №2 будет простаивать:

1. `fixtures/repo_context.settlement.json` (№1).
2. `golden/settlement-001/` проходит base = 0 и oracle = 1 через `verify_case` (№3).
3. `write_task_folder` собирает `task/` из `CaseDraft` (№1).
4. Раздел «Статус модулей» в README заполнен.

## Ветки и коммиты

- Ветка на человека: `p1/...`, `p2/...`, `p3/...`, `p4/...`. Мерж в `main` маленькими кусками, не реже раза в пару часов.
- Перед мержем: `python -m pytest` зелёный (тесты с маркерами `docker` и `llm` можно пропускать через `-m "not docker and not llm"`).
- Трогаем только свои файлы из таблицы в README. Нужна правка в чужом модуле — пишем владельцу.

## Контракты

- `harness/contracts.py` — единственное место обмена данными.
- Добавить поле со значением по умолчанию: можно, сообщить в чат.
- Переименовать, удалить, сменить тип, поменять сигнатуру публичной функции-заглушки: только после согласия в чате.
- После любого изменения контрактов — обновить фикстуры в том же коммите.

## Файлы с частыми конфликтами

`requirements*.txt`, `pyproject.toml`, `.gitignore`, `README.md` (кроме таблицы статусов): правки небольшими отдельными коммитами, сразу в `main`.

## Работа без чужого кода

- Используем фикстуры из `fixtures/`, а не ждём реализации.
- Свои тестовые данные кладём в `tests/<модуль>/data/`.
- Материалы организаторов не коммитим: `materials/` в `.gitignore`.

## Безопасность

- Ключи LLM только в `.env` или переменных окружения; никогда в коде, логах, evidence и фикстурах.
- Сгенерированный LLM код исполняется только в контейнере с `--network none`.
- Содержимое `DOCS/imported/` и подобных файлов из репозитория не отправляется в LLM.
