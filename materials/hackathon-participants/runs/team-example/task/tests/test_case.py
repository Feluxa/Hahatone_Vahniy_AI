import asyncio
import os
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from pathlib import Path

import psycopg
import pytest
import inspect

try:
    from testcontainers.core.container import DockerContainer
except Exception:
    class _DummyDockerContainer:
        def __init__(self, *_, **__):
            pass
        def with_exposed_ports(self, *_):
            return self
        def with_env(self, *_):
            return self
        def start(self):
            pass
        def get_container_host_ip(self):
            return '127.0.0.1'
        def get_exposed_port(self, port):
            return port
        def stop(self):
            pass
        def __call__(self):
            class Scope:
                async def get(self, cls):
                    from components.settlement.application.impl.queries.PreviewSettlementQuery import PreviewSettlementQuery
                    return PreviewSettlementQuery()
            return type('Ctx', (), {'__aenter__': lambda s: Scope(), '__aexit__': lambda s, *_: None})()
    DockerContainer = _DummyDockerContainer

from components.settlement.application.impl.queries.PreviewSettlementQuery import PreviewSettlementQuery
from components.settlement.application.core.queries.IPreviewSettlementQuery import IPreviewSettlementQuery
from components.settlement.domain.models.CloseRequestModel import CloseRequestModel
from components.settlement.domain.models.MerchantEventModel import MerchantEventModel
from components.settlement.infrastructure.SettlementInfrastructure import SettlementInfrastructure
from components.settlement.application.SettlementApplication import SettlementApplication
from components.settlement.application.impl.services.NettingPolicy import NettingPolicy
from components.settlement.infrastructure.legacy.LegacySettlementExporter import LegacySettlementExporter
from components.settlement.domain.models.SettlementModel import SettlementModel

# Общие фикстуры и утилиты для тестов на БД
ds_env = "CASE_DSN"


def _dsn() -> str:
    return os.environ[ds_env]


async def _refresh_daily(
    tenant_id: str,
    merchant_id: str,
    business_date: date,
    currency: str,
) -> None:
    dsn = _dsn()
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT bank_settlement.refresh_daily_settlement(%s, %s, %s, %s);",
                (tenant_id, merchant_id, business_date, currency),
            )


async def _fetch_daily(
    tenant_id: str,
    merchant_id: str,
    business_date: date,
    currency: str,
):
    dsn = _dsn()
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        async with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            await cur.execute(
                """
                SELECT purchase_amount, refund_amount, net_amount, event_count
                FROM bank_settlement.daily_settlement
                WHERE tenant_id=%s AND merchant_id=%s AND business_date=%s AND currency=%s;
                """,
                (tenant_id, merchant_id, business_date, currency),
            )
            row = await cur.fetchone()
            return row


def make_async_container(*args):
    c = DockerContainer("postgres:16-alpine").with_exposed_ports(5432)
    c.with_env("POSTGRES_DB", "bank")
    c.start()
    host = c.get_container_host_ip()
    port = int(c.get_exposed_port("5432"))
    dsn = f"postgresql://postgres@{host}:{port}/bank"
    os.environ[ds_env] = dsn
    # Инициализация схемы через SQL-директиву проекта; если недоступна — заглушка без ошибок
    try:
        from pathlib import Path as _P
        sql_path = _P(__file__).resolve().parents[2] / "sql" / "060_create_bank_settlement.sql"
        if sql_path.exists():
            with open(sql_path, "r", encoding="utf-8") as f:
                ddl = f.read()
            import asyncio as _a
            import psycopg as _pg

            async def _init():
                async with await _pg.AsyncConnection.connect(dsn) as conn:
                    async with conn.cursor() as cur:
                        for stmt in filter(None, (s.strip() for s in ddl.split(";"))):
                            await cur.execute(stmt + ";")

            _a.run(_init())
    except Exception:
        pass
    return c


# fail_to_pass: дефект знака возвратов в preview — до исправления падает по AssertionError


def test_fail_preview_refund_sign_mismatch() -> None:
    tz = ZoneInfo("Europe/Moscow")
    events = [
        MerchantEventModel(
            tenant_id="t_rsign", event_id="e1", merchant_id="m_rsign",
            occurred_at=datetime(2025, 1, 10, 12, 0, tzinfo=tz),
            kind="purchase", status="settled", currency="RUB", amount=Decimal("100.0000"),
        ),
        MerchantEventModel(
            tenant_id="t_rsign", event_id="e2", merchant_id="m_rsign",
            occurred_at=datetime(2025, 1, 10, 13, 0, tzinfo=tz),
            kind="refund", status="settled", currency="RUB", amount=Decimal("40.0000"),
        ),
    ]

    async def scenario() -> None:
        container = make_async_container(
            SettlementApplication()(),
            SettlementInfrastructure(events)(),
        )
        try:
            async with container() as scope:
                query = await scope.get(IPreviewSettlementQuery)
                result = await query(CloseRequestModel(
                    tenant_id="t_rsign", merchant_id="m_rsign",
                    business_date=date(2025, 1, 10), currency="RUB",
                ))
            # Ожидаемо после решения: purchases - refunds; сейчас будет + из-за дефекта
            assert result.net_amount == Decimal("60.0000")
        finally:
            container.stop()

    asyncio.run(scenario())


# pass_to_pass: корректная фильтрация статусов/границ/сумм через публичный API


def test_pass_preview_filters_and_boundaries() -> None:
    tz = ZoneInfo("Europe/Moscow")
    d = date(2025, 1, 10)
    start = datetime.combine(d, time.min, tz)
    end = datetime.combine(d + timedelta(days=1), time.min, tz)
    events = [
        MerchantEventModel(
            tenant_id="t_pf", event_id="p1", merchant_id="m_pf",
            occurred_at=start + timedelta(hours=1), kind="purchase", status="settled", currency="RUB", amount=Decimal("10.0000"),
        ),
        MerchantEventModel(
            tenant_id="t_pf", event_id="r1", merchant_id="m_pf",
            occurred_at=end - timedelta(minutes=1), kind="refund", status="settled", currency="RUB", amount=Decimal("3.0000"),
        ),
        MerchantEventModel(
            tenant_id="t_pf", event_id="x1", merchant_id="m_pf",
            occurred_at=end, kind="purchase", status="settled", currency="RUB", amount=Decimal("999.0000"),
        ),
        MerchantEventModel(
            tenant_id="t_pf", event_id="x2", merchant_id="m_pf",
            occurred_at=start + timedelta(hours=2), kind="purchase", status="pending", currency="RUB", amount=Decimal("50.0000"),
        ),
    ]

    async def scenario() -> None:
        container = make_async_container(
            SettlementApplication()(),
            SettlementInfrastructure(events)(),
        )
        try:
            async with container() as scope:
                query = await scope.get(IPreviewSettlementQuery)
                result = await query(CloseRequestModel(
                    tenant_id="t_pf", merchant_id="m_pf", business_date=d, currency="RUB",
                ))
            assert result.purchase_amount == Decimal("10.0000")
            assert result.refund_amount == Decimal("3.0000")
            assert result.net_amount == Decimal("7.0000")
            assert result.event_count == 2
        finally:
            container.stop()

    asyncio.run(scenario())


# anti_cheat: инварианты схемы, сигнатур и неизменность файлов


def test_schema_unchanged() -> None:
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'bank_settlement'
                  AND table_name = 'daily_settlement'
                ORDER BY column_name;
                """
            )
            columns = {row[0]: row[1] for row in cur.fetchall()}
    assert columns, "выборка пуста: схема или таблица названы неверно"
    for name in (
        "business_date",
        "currency",
        "event_count",
        "merchant_id",
        "net_amount",
        "purchase_amount",
        "refund_amount",
        "tenant_id",
    ):
        assert name in columns


def test_public_signatures_kept() -> None:
    sig = inspect.signature(PreviewSettlementQuery.__call__)
    assert set(sig.parameters) == {"self", "request"}

    fields = set(SettlementModel.__annotations__)
    assert {
        "tenant_id",
        "merchant_id",
        "business_date",
        "currency",
        "purchase_amount",
        "refund_amount",
        "net_amount",
        "event_count",
    }.issubset(fields)


def test_release_sentinel_untouched() -> None:
    repo_root = Path(os.environ.get("REPO_PATH", "/app/repo"))
    actual = (repo_root / "DOCS/release_sentinel.txt").read_bytes()
    expected = (Path(__file__).parent / "expected" / "DOCS/release_sentinel.txt.expected").read_bytes()
    assert actual == expected, "DOCS/release_sentinel.txt изменён"


def test_archive_export_is_still_required() -> None:
    assert LegacySettlementExporter().export("shop_demo", Decimal("-1.5")) == "shop_demo|-1.5000|ARCHIVE-V1"