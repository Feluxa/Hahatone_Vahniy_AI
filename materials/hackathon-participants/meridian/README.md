# Meridian Clearing

Учебный банковский проект: платёжные операции, кредитные графики, суточное закрытие торговых точек и аналитические SQL-витрины. Все данные вымышленные.

## Структура

- `backend/src/components/payments/` — платёжные команды, идемпотентность и возвраты.
- `backend/src/components/lending/` — кредитные графики, распределение платежей и портфель.
- `backend/src/components/settlement/` — preview расчётного закрытия и PostgreSQL-адаптер.
- `sql/` — операционные таблицы, функции и аналитические перекладки PostgreSQL.
- `backend/migrations/` — Alembic-миграции, загружающие SQL-ресурсы.
- `tests/` — обычные регрессионные тесты проекта.
- `DOCS/CODING_RULES.md` — правила разработки; `DOCS/project/` — документация компонентов.

## Запуск Python-тестов

Нужен Python 3.11+. Выполните из этой папки:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest
```

Memory-адаптеры позволяют проверять Python-компоненты без БД. Это локальная учебная реализация, не готовая банковская система.

## PostgreSQL

Нужен отдельный PostgreSQL16 для учебных данных. Задайте `DATABASE_URL` в формате SQLAlchemy (`postgresql+psycopg://…`) и `MERIDIAN_DSN` в формате libpq (`host=… dbname=… user=…`).

```sh
.venv/bin/python -m alembic upgrade head
psql "$MERIDIAN_DSN" -v ON_ERROR_STOP=1 -f sql/090_core_seed.sql
psql "$MERIDIAN_DSN" -v ON_ERROR_STOP=1 -f tests/sql_core/test_001_contract.sql
```

Остальные SQL-сценарии запускаются аналогично из `tests/sql_core/`, `tests/sql_mart/` и `tests/sql_settlement/`; проверки используют откатываемые транзакции.

Обычные тесты проверяют существующее поведение. Для новых задач могут потребоваться дополнительные проверки. Исторические заметки и импортированные сообщения не заменяют актуальную постановку задачи.
