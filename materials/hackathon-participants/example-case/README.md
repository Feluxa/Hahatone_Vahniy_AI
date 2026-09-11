# Пример готового кейса

Это самостоятельный маленький кейс про полуоткрытый числовой интервал. Все файлы заполнены; его можно собрать и проверить. Автор в манифесте вымышленный.

## Что лежит в папке

```text
example-case/
├── README.md                       # Пояснение к примеру
├── task.toml                       # Метаданные и пять идентификаторов тестов
├── instruction.md                  # Задание для решающего AI
├── environment/
│   ├── Dockerfile                  # Python и зависимости
│   ├── requirements.txt            # Зафиксированная версия pytest
│   └── repo/
│       ├── interval.py             # Исходный код с дефектом
│       └── legacy.py               # Существующее поведение, менять нельзя
├── tests/
│   ├── test.sh                     # Запуск проверки, запись 0 или 1
│   ├── test_interval.py            # Пять тестов из task.toml
│   └── legacy.py.expected          # Эталон неизменяемого файла
└── solution/
    └── solve.sh                    # Исправление исходного кода
```

В создаваемом вами результате такая папка называется `task/`. Отчёты запусков сохраняются отдельно в `evidence/`. README здесь поясняет учебный пример и не является обязательным файлом кейса.

`interval.py` ошибочно включает правую границу. Два теста выявляют ошибку, два проверяют сохранность существующего поведения и интерфейса, один — запрет изменения `legacy.py`. После эталонного решения проходят все пять.

AI, решающий этот кейс, получает только `instruction.md` и содержимое `environment/repo/`. Доступ ко всем файлам примера предоставлен вам как разработчикам генератора, чтобы показать устройство пакета.

## Сборка и запуск

Нужен запущенный Docker. Команды выполняются из `example-case/` в POSIX-совместимой оболочке. Загрузка образа и установка зависимостей при сборке требуют сети; сами проверки запускаются без неё.

```sh
docker build -t interval-case-example environment

# Результаты вне папки кейса.
CASE_EVIDENCE="$(mktemp -d)"
mkdir -p "$CASE_EVIDENCE/base" "$CASE_EVIDENCE/oracle"

# Исходное состояние: 2 failed, 3 passed, reward = 0.
docker run --rm --network none \
  -v "$PWD/tests:/tests:ro" \
  -v "$CASE_EVIDENCE/base:/logs" \
  interval-case-example sh /tests/test.sh
cat "$CASE_EVIDENCE/base/verifier/reward.txt"

# Новый контейнер: применить решение, затем проверить.
# Ожидаются 5 passed и reward = 1.
docker run --rm --network none \
  -v "$PWD/tests:/tests:ro" \
  -v "$PWD/solution:/solution:ro" \
  -v "$CASE_EVIDENCE/oracle:/logs" \
  interval-case-example sh -c 'sh /solution/solve.sh && sh /tests/test.sh'
cat "$CASE_EVIDENCE/oracle/verifier/reward.txt"
```

В каждом каталоге `verifier/` появятся `reward.txt`, `pytest.log` и `tests.xml`. Скрипт сообщает результат через файл reward; сам код завершения контейнера не заменяет этот результат. Повтор тех же команд запускает независимые свежие контейнеры.

Для отдельного списка используйте его полные идентификаторы из `task.toml`. Например, проверка двух `pass_to_pass` на базе:

```sh
docker run --rm --network none \
  -v "$PWD/tests:/tests:ro" \
  interval-case-example sh -c 'cd / && python -m pytest --rootdir=/ -p no:cacheprovider \
    tests/test_interval.py::test_existing_membership_and_api \
    tests/test_interval.py::test_invalid_bounds'
```

Тем же способом запускаются остальные списки. Для исправленного состояния добавьте монтирование `solution/` и выполните `sh /solution/solve.sh` перед pytest. Ожидаемые исходы: на базе `fail_to_pass` — 2 failed, остальные списки — passed; после решения все списки — passed.

После знакомства образ можно удалить командой `docker image rm interval-case-example`. Путь к сохранённым результатам находится в переменной `CASE_EVIDENCE`.
