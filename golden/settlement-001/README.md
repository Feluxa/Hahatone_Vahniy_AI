# Эталонный кейс settlement-001 (пишется руками)

Владелец: №3. Структура — как у `task/` из PROTOCOL.md:

```text
task.toml
instruction.md
environment/Dockerfile
environment/repo/            # чистая копия meridian (не коммитим, собирается скриптом из materials/)
tests/test.sh
tests/conftest.py
tests/test_*.py
solution/solve.sh
```

Список тестов и мутантов — раздел 6 плана (`docs/PLAN.docx`).

Критерий готовности на сегодня: `verify_case` на этой папке даёт base reward 0 и oracle reward 1.
Завтра этот кейс — few-shot образец для промптов №2.
