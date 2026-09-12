# Фикстуры

Примеры данных в формате `harness/contracts.py`. Нужны, чтобы каждый мог работать и тестироваться, не дожидаясь чужого кода.

| Файл | Структура | Кто выдаёт настоящие данные |
|---|---|---|
| `case_input.example.json` | `CaseInput` | №1, `protocol/input.py` |
| `repo_context.example.json` | `RepoContext` (сокращённый пример, содержимое файлов заменено) | №1, `repo/context.py` |
| `case_draft.example.json` | `CaseDraft` | №2 (LLM), №3 (эталон в `golden/`) |
| `runs.example.json` | `{"runs": [RunResult]}` | №3, `verify/runs.py` |
| `verdict.example.json` | `Verdict` | №3, `verify/verdict.py` |
| `llm_usage.example.json` | `UsageLog` | №2, `llm/client.py` |
| `result.example.json` | `CaseResult` | №1, `protocol/output.py` |

Настоящие фикстуры, которые нужно положить сюда к концу сегодняшнего дня:

- `repo_context.settlement.json` — вывод `build_context` на meridian с брифом settlement-001 (№1);
- `runs.golden.json` и `verdict.golden.json` — прогон эталонного кейса (№3).

`repo_context.settlement.json` сравнивается с текущим выводом в `tests/repo/test_context.py`, поэтому после правки эвристики отбора его надо перегенерировать (нужны выложенные `materials/`):

```sh
.venv/Scripts/python.exe -m tests.repo.regen_settlement_fixture
```

Все файлы проверяются в `tests/test_contracts.py`: при изменении контрактов обновляйте их в том же коммите.
