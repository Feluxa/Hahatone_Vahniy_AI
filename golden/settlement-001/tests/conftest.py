"""Автоматически сгенерированный conftest.py для окружения с PostgreSQL и настройкой путей."""
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Настройка путей pythonpath
PYTHONPATHS = ['backend/src']
for p in PYTHONPATHS:
    full_path = p if os.path.isabs(p) else os.path.join("/app/repo", p)
    if full_path not in sys.path:
        sys.path.insert(0, full_path)

NEEDS_POSTGRES = True
POSTGRES_MAJOR = 16
MIGRATION_CMD = ['python', '-m', 'alembic', 'upgrade', 'head']
SEED_SQL_FILES = ['sql/090_core_seed.sql']
ENV_VARS = {}

for _k, _v in ENV_VARS.items():
    os.environ.setdefault(_k, _v)


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _run_as_postgres(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Запуск команды от пользователя postgres (если текущий пользователь root)."""
    if os.name != "nt" and os.geteuid() == 0:
        escaped = " ".join(f'"{c}"' for c in cmd)
        return subprocess.run(["su", "-s", "/bin/sh", "postgres", "-c", escaped], check=True, **kwargs)
    return subprocess.run(cmd, check=True, **kwargs)


@pytest.fixture(scope="session", autouse=True)
def postgres_service():
    if not NEEDS_POSTGRES:
        yield None
        return

    port = _get_free_port()
    pg_data = Path("/tmp/pgdata")
    pg_log = Path("/tmp/pg.log")

    if pg_data.exists():
        shutil.rmtree(pg_data)

    pg_bin = Path(f"/usr/lib/postgresql/{POSTGRES_MAJOR}/bin")
    if not pg_bin.exists():
        pg_bin = Path("/usr/lib/postgresql/16/bin")

    initdb_bin = str(pg_bin / "initdb") if (pg_bin / "initdb").exists() else "initdb"
    pg_ctl_bin = str(pg_bin / "pg_ctl") if (pg_bin / "pg_ctl").exists() else "pg_ctl"
    createdb_bin = str(pg_bin / "createdb") if (pg_bin / "createdb").exists() else "createdb"
    psql_bin = str(pg_bin / "psql") if (pg_bin / "psql").exists() else "psql"

    # Создаем директорию данных с правами 0700 для пользователя postgres
    if os.name != "nt" and os.geteuid() == 0:
        subprocess.run(["mkdir", "-p", str(pg_data)], check=True)
        subprocess.run(["chown", "-R", "postgres:postgres", str(pg_data)], check=True)
        subprocess.run(["chmod", "0700", str(pg_data)], check=True)
        _run_as_postgres([initdb_bin, "-D", str(pg_data), "--no-sync", "-A", "trust", "-U", "postgres"])
        _run_as_postgres([
            pg_ctl_bin, "-D", str(pg_data), "-l", str(pg_log),
            "-o", f"-p {port} -k /tmp -c fsync=off -c synchronous_commit=off -c full_page_writes=off",
            "start",
        ])
    else:
        pg_data.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(str(pg_data), 0o700)
        subprocess.run([initdb_bin, "-D", str(pg_data), "--no-sync", "-A", "trust", "-U", "postgres"], check=True)
        subprocess.run([
            pg_ctl_bin, "-D", str(pg_data), "-l", str(pg_log),
            "-o", f"-p {port} -k /tmp -c fsync=off -c synchronous_commit=off -c full_page_writes=off",
            "start",
        ], check=True)

    # Ожидание готовности сервера
    started = False
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                started = True
                break
        except OSError:
            time.sleep(0.1)

    if not started:
        log_content = pg_log.read_text(errors="replace") if pg_log.exists() else "No log"
        raise RuntimeError(f"PostgreSQL failed to start on port {port}. Log:\n{log_content}")

    # Создаем базу данных
    db_name = "meridian"
    cmd_create = [createdb_bin, "-h", "127.0.0.1", "-p", str(port), "-U", "postgres", db_name]
    subprocess.run(cmd_create, check=True)

    # Выставляем переменные окружения
    db_url = f"postgresql+psycopg://postgres@127.0.0.1:{port}/{db_name}"
    dsn = f"host=127.0.0.1 port={port} dbname={db_name} user=postgres"
    os.environ["DATABASE_URL"] = db_url
    os.environ["MERIDIAN_DSN"] = dsn

    # Выполняем миграции ПОСЛЕ решения
    if MIGRATION_CMD:
        subprocess.run(MIGRATION_CMD, cwd="/app/repo", check=True)

    # Накатываем seed SQL файлы
    for seed_file in SEED_SQL_FILES:
        seed_path = Path("/app/repo") / seed_file if not os.path.isabs(seed_file) else Path(seed_file)
        if seed_path.exists():
            subprocess.run(
                [psql_bin, "-h", "127.0.0.1", "-p", str(port), "-U", "postgres", "-d", db_name, "-v", "ON_ERROR_STOP=1", "-f", str(seed_path)],
                check=True,
            )

    yield {
        "port": port,
        "database_url": db_url,
        "dsn": dsn,
    }

    # Остановка PostgreSQL
    stop_cmd = [pg_ctl_bin, "-D", str(pg_data), "-m", "immediate", "stop"]
    if os.name != "nt" and os.geteuid() == 0:
        _run_as_postgres(stop_cmd)
    else:
        subprocess.run(stop_cmd, check=False)
