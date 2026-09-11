import asyncio
import inspect
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
from dishka import make_async_container

from components.settlement.application.SettlementApplication import SettlementApplication
from components.settlement.application.core.queries.IPreviewSettlementQuery import IPreviewSettlementQuery
from components.settlement.domain.models.CloseRequestModel import CloseRequestModel
from components.settlement.domain.models.MerchantEventModel import MerchantEventModel
from components.settlement.domain.models.SettlementModel import SettlementModel
from components.settlement.infrastructure.SettlementInfrastructure import SettlementInfrastructure
from components.settlement.infrastructure.legacy.LegacySettlementExporter import LegacySettlementExporter


# ============================================================================
# fail_to_pass (дефекты, обязаны падать по AssertionError на base)
# ============================================================================

def test_sql_refund_reduces_net() -> None:
    """Проверяет в SQL, что покупка 100 и возврат 30 дают net=70 при наличии события на границе суток."""
    dsn = os.environ.get("MERIDIAN_DSN", "host=127.0.0.1 port=5432 dbname=meridian user=postgres")
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO bank_settlement.merchant_event (
                    tenant_id, event_id, merchant_id, occurred_at, kind, status, currency, amount
                ) VALUES
                    ('t_sql_refund', 'ev_p1', 'm_sql_refund', '2025-01-10 12:00:00+03', 'purchase', 'settled', 'RUB', 100.00),
                    ('t_sql_refund', 'ev_r1', 'm_sql_refund', '2025-01-10 14:00:00+03', 'refund', 'settled', 'RUB', 30.00),
                    ('t_sql_refund', 'ev_next_mid', 'm_sql_refund', '2025-01-11 00:00:00+03', 'purchase', 'settled', 'RUB', 50.00)
                ON CONFLICT (tenant_id, event_id) DO NOTHING;
            """)
            cur.execute("""
                SELECT purchase_amount, refund_amount, net_amount, event_count
                FROM bank_settlement.refresh_daily_settlement('t_sql_refund', 'm_sql_refund', '2025-01-10', 'RUB');
            """)
            row = cur.fetchone()
            assert row is not None
            purchase, refund, net, count = row
            # На base из-за <= v_end покупка в 00:00 11-го попадает в 10-е, давая net=120 и count=3
            assert net == Decimal("70.0000"), f"Expected net 70.0000, got {net}"
            assert count == 2, f"Expected 2 events, got {count}"
            assert purchase == Decimal("100.0000")
            assert refund == Decimal("30.0000")


def test_preview_refund_reduces_net() -> None:
    """Проверяет в Python preview, что возврат уменьшает чистый итог (net = purchase - refund)."""
    async def scenario() -> None:
        events = [
            MerchantEventModel(
                tenant_id="t_prev_ref", event_id="e1", merchant_id="m1",
                occurred_at=datetime.fromisoformat("2025-01-10T12:00:00+03:00"),
                kind="purchase", status="settled", currency="RUB", amount=Decimal("100.0000"),
            ),
            MerchantEventModel(
                tenant_id="t_prev_ref", event_id="e2", merchant_id="m1",
                occurred_at=datetime.fromisoformat("2025-01-10T14:00:00+03:00"),
                kind="refund", status="settled", currency="RUB", amount=Decimal("30.0000"),
            ),
        ]
        container = make_async_container(
            SettlementApplication()(), SettlementInfrastructure(events)(),
        )
        try:
            async with container() as scope:
                query = await scope.get(IPreviewSettlementQuery)
                result = await query(CloseRequestModel(
                    tenant_id="t_prev_ref", merchant_id="m1",
                    business_date=date(2025, 1, 10), currency="RUB",
                ))
            # На base возвраты прибавляются: net=130 вместо 70
            assert result.net_amount == Decimal("70.0000"), f"Expected net 70, got {result.net_amount}"
            assert result.event_count == 2
            assert result.purchase_amount == Decimal("100.0000")
            assert result.refund_amount == Decimal("30.0000")
        finally:
            await container.close()

    asyncio.run(scenario())


def test_sql_next_midnight_excluded() -> None:
    """Проверяет, что событие ровно в 00:00 следующего дня исключается из текущего дня в SQL."""
    dsn = os.environ.get("MERIDIAN_DSN", "host=127.0.0.1 port=5432 dbname=meridian user=postgres")
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO bank_settlement.merchant_event (
                    tenant_id, event_id, merchant_id, occurred_at, kind, status, currency, amount
                ) VALUES
                    ('t_sql_mid', 'ev_base', 'm_sql_mid', '2025-01-10 12:00:00+03', 'purchase', 'settled', 'RUB', 100.00),
                    ('t_sql_mid', 'ev_next', 'm_sql_mid', '2025-01-11 00:00:00+03', 'purchase', 'settled', 'RUB', 1000.00)
                ON CONFLICT (tenant_id, event_id) DO NOTHING;
            """)
            cur.execute("""
                SELECT purchase_amount, net_amount, event_count
                FROM bank_settlement.refresh_daily_settlement('t_sql_mid', 'm_sql_mid', '2025-01-10', 'RUB');
            """)
            row = cur.fetchone()
            assert row is not None
            purchase, net, count = row
            # На base из-за <= v_end net=1100 и count=2
            assert purchase == Decimal("100.0000"), f"Next midnight should be excluded, got purchase {purchase}"
            assert net == Decimal("100.0000")
            assert count == 1, f"Expected 1 event, got {count}"


def test_preview_matches_sql() -> None:
    """Проверяет строгое побайтовое совпадение итогов preview и SQL на общем наборе событий."""
    dsn = os.environ.get("MERIDIAN_DSN", "host=127.0.0.1 port=5432 dbname=meridian user=postgres")
    tenant = "t_match"
    merchant = "m_match"
    b_date = date(2025, 1, 10)
    curr = "RUB"

    events = [
        MerchantEventModel(
            tenant_id=tenant, event_id="ev_m1", merchant_id=merchant,
            occurred_at=datetime.fromisoformat("2025-01-10T00:00:00+03:00"),
            kind="purchase", status="settled", currency=curr, amount=Decimal("200.0000"),
        ),
        MerchantEventModel(
            tenant_id=tenant, event_id="ev_m2", merchant_id=merchant,
            occurred_at=datetime.fromisoformat("2025-01-10T15:30:00+03:00"),
            kind="refund", status="settled", currency=curr, amount=Decimal("50.0000"),
        ),
        MerchantEventModel(
            tenant_id=tenant, event_id="ev_m3_mid", merchant_id=merchant,
            occurred_at=datetime.fromisoformat("2025-01-11T00:00:00+03:00"),
            kind="purchase", status="settled", currency=curr, amount=Decimal("999.0000"),
        ),
    ]

    # 1. SQL
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            for ev in events:
                cur.execute("""
                    INSERT INTO bank_settlement.merchant_event (
                        tenant_id, event_id, merchant_id, occurred_at, kind, status, currency, amount
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, event_id) DO NOTHING;
                """, (ev.tenant_id, ev.event_id, ev.merchant_id, ev.occurred_at, ev.kind, ev.status, ev.currency, ev.amount))
            cur.execute("""
                SELECT purchase_amount, refund_amount, net_amount, event_count
                FROM bank_settlement.refresh_daily_settlement(%s, %s, %s, %s);
            """, (tenant, merchant, b_date, curr))
            sql_row = cur.fetchone()
            assert sql_row is not None

    # 2. Preview
    async def get_preview():
        container = make_async_container(
            SettlementApplication()(), SettlementInfrastructure(events)(),
        )
        try:
            async with container() as scope:
                query = await scope.get(IPreviewSettlementQuery)
                return await query(CloseRequestModel(
                    tenant_id=tenant, merchant_id=merchant,
                    business_date=b_date, currency=curr,
                ))
        finally:
            await container.close()

    preview_res = asyncio.run(get_preview())

    # Сравнение всех полей
    assert preview_res.purchase_amount == sql_row[0]
    assert preview_res.refund_amount == sql_row[1]
    assert preview_res.net_amount == sql_row[2]
    assert preview_res.event_count == sql_row[3]


# ============================================================================
# pass_to_pass (существующее поведение, проходит до и после решения)
# ============================================================================

def test_preview_purchases_and_real_di_resolution() -> None:
    """Существующий тест проекта: preview одиночной покупки через DI."""
    async def scenario() -> None:
        event = MerchantEventModel(
            tenant_id="tenant_p2p_demo", event_id="event_demo", merchant_id="shop_demo",
            occurred_at=datetime.fromisoformat("2025-01-10T12:00:00+03:00"),
            kind="purchase", status="settled", currency="RUB", amount=Decimal("12.4500"),
        )
        container = make_async_container(
            SettlementApplication()(), SettlementInfrastructure([event])(),
        )
        try:
            async with container() as scope:
                query = await scope.get(IPreviewSettlementQuery)
                result = await query(CloseRequestModel(
                    tenant_id="tenant_p2p_demo", merchant_id="shop_demo",
                    business_date=date(2025, 1, 10), currency="RUB",
                ))
            assert result.net_amount == Decimal("12.4500")
            assert result.event_count == 1
        finally:
            await container.close()

    asyncio.run(scenario())


def test_sql_purchase_close() -> None:
    """Существующий тест закрытия покупки в SQL."""
    dsn = os.environ.get("MERIDIAN_DSN", "host=127.0.0.1 port=5432 dbname=meridian user=postgres")
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO bank_settlement.merchant_event (
                    tenant_id, event_id, merchant_id, occurred_at, kind, status, currency, amount
                ) VALUES ('t_sql_smoke', 'smoke_p', 's_smoke', '2025-01-10 10:00+03', 'purchase', 'settled', 'RUB', 42.00)
                ON CONFLICT (tenant_id, event_id) DO NOTHING;
            """)
            cur.execute("""
                SELECT net_amount, event_count
                FROM bank_settlement.refresh_daily_settlement('t_sql_smoke', 's_smoke', '2025-01-10', 'RUB');
            """)
            row = cur.fetchone()
            assert row is not None
            assert row[0] == Decimal("42.0000")
            assert row[1] == 1


def test_start_midnight_included() -> None:
    """Событие ровно в 00:00 текущего дня включается в расчет."""
    dsn = os.environ.get("MERIDIAN_DSN", "host=127.0.0.1 port=5432 dbname=meridian user=postgres")
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO bank_settlement.merchant_event (
                    tenant_id, event_id, merchant_id, occurred_at, kind, status, currency, amount
                ) VALUES ('t_start_mid', 'ev_start', 'm_start', '2025-01-10 00:00:00+03', 'purchase', 'settled', 'RUB', 15.00)
                ON CONFLICT (tenant_id, event_id) DO NOTHING;
            """)
            cur.execute("""
                SELECT net_amount, event_count
                FROM bank_settlement.refresh_daily_settlement('t_start_mid', 'm_start', '2025-01-10', 'RUB');
            """)
            row = cur.fetchone()
            assert row is not None
            assert row[0] == Decimal("15.0000")
            assert row[1] == 1


def test_non_settled_ignored() -> None:
    """События в статусах pending и void игнорируются."""
    dsn = os.environ.get("MERIDIAN_DSN", "host=127.0.0.1 port=5432 dbname=meridian user=postgres")
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO bank_settlement.merchant_event (
                    tenant_id, event_id, merchant_id, occurred_at, kind, status, currency, amount
                ) VALUES
                    ('t_status', 'ev_ok', 'm_status', '2025-01-10 11:00:00+03', 'purchase', 'settled', 'RUB', 10.00),
                    ('t_status', 'ev_pending', 'm_status', '2025-01-10 11:10:00+03', 'purchase', 'pending', 'RUB', 50.00),
                    ('t_status', 'ev_void', 'm_status', '2025-01-10 11:20:00+03', 'purchase', 'void', 'RUB', 70.00)
                ON CONFLICT (tenant_id, event_id) DO NOTHING;
            """)
            cur.execute("""
                SELECT net_amount, event_count
                FROM bank_settlement.refresh_daily_settlement('t_status', 'm_status', '2025-01-10', 'RUB');
            """)
            row = cur.fetchone()
            assert row is not None
            assert row[0] == Decimal("10.0000")
            assert row[1] == 1


def test_timezone_normalization() -> None:
    """Событие с таймзоной UTC приводится к Europe/Moscow."""
    dsn = os.environ.get("MERIDIAN_DSN", "host=127.0.0.1 port=5432 dbname=meridian user=postgres")
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            # 2025-01-10 20:00 UTC = 2025-01-10 23:00 MSK (входит в 10-е число)
            cur.execute("""
                INSERT INTO bank_settlement.merchant_event (
                    tenant_id, event_id, merchant_id, occurred_at, kind, status, currency, amount
                ) VALUES ('t_tz', 'ev_tz', 'm_tz', '2025-01-10 20:00:00+00', 'purchase', 'settled', 'RUB', 25.00)
                ON CONFLICT (tenant_id, event_id) DO NOTHING;
            """)
            cur.execute("""
                SELECT net_amount, event_count
                FROM bank_settlement.refresh_daily_settlement('t_tz', 'm_tz', '2025-01-10', 'RUB');
            """)
            row = cur.fetchone()
            assert row is not None
            assert row[0] == Decimal("25.0000")
            assert row[1] == 1


# ============================================================================
# anti_cheat (защитные проверки и инварианты)
# ============================================================================

def test_isolation_tenant_merchant_currency() -> None:
    """События других арендаторов, мерчантов и валют изолированы."""
    dsn = os.environ.get("MERIDIAN_DSN", "host=127.0.0.1 port=5432 dbname=meridian user=postgres")
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO bank_settlement.merchant_event (
                    tenant_id, event_id, merchant_id, occurred_at, kind, status, currency, amount
                ) VALUES
                    ('t_iso_1', 'e_iso_1', 'm_iso_target', '2025-01-10 12:00:00+03', 'purchase', 'settled', 'RUB', 10.00),
                    ('t_iso_2', 'e_iso_2', 'm_iso_target', '2025-01-10 12:00:00+03', 'purchase', 'settled', 'RUB', 99.00),
                    ('t_iso_1', 'e_iso_3', 'm_iso_other',  '2025-01-10 12:00:00+03', 'purchase', 'settled', 'RUB', 88.00),
                    ('t_iso_1', 'e_iso_4', 'm_iso_target', '2025-01-10 12:00:00+03', 'purchase', 'settled', 'USD', 77.00)
                ON CONFLICT (tenant_id, event_id) DO NOTHING;
            """)
            cur.execute("""
                SELECT net_amount, event_count
                FROM bank_settlement.refresh_daily_settlement('t_iso_1', 'm_iso_target', '2025-01-10', 'RUB');
            """)
            row = cur.fetchone()
            assert row is not None
            assert row[0] == Decimal("10.0000")
            assert row[1] == 1


def test_reclose_replaces_same_date_only() -> None:
    """Повторное закрытие перезаписывает ту же дату и не удаляет соседние даты."""
    dsn = os.environ.get("MERIDIAN_DSN", "host=127.0.0.1 port=5432 dbname=meridian user=postgres")
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO bank_settlement.merchant_event (
                    tenant_id, event_id, merchant_id, occurred_at, kind, status, currency, amount
                ) VALUES
                    ('t_reclose', 'e_d1', 'm_reclose', '2025-01-10 12:00:00+03', 'purchase', 'settled', 'RUB', 10.00),
                    ('t_reclose', 'e_d2', 'm_reclose', '2025-01-11 12:00:00+03', 'purchase', 'settled', 'RUB', 20.00)
                ON CONFLICT (tenant_id, event_id) DO NOTHING;
            """)
            # Закрываем обе даты
            cur.execute("SELECT * FROM bank_settlement.refresh_daily_settlement('t_reclose', 'm_reclose', '2025-01-10', 'RUB');")
            cur.execute("SELECT * FROM bank_settlement.refresh_daily_settlement('t_reclose', 'm_reclose', '2025-01-11', 'RUB');")

            # Добавляем событие в 10-е и повторно закрываем 10-е
            cur.execute("""
                INSERT INTO bank_settlement.merchant_event (
                    tenant_id, event_id, merchant_id, occurred_at, kind, status, currency, amount
                ) VALUES ('t_reclose', 'e_d1_new', 'm_reclose', '2025-01-10 15:00:00+03', 'purchase', 'settled', 'RUB', 5.00);
            """)
            cur.execute("SELECT net_amount FROM bank_settlement.refresh_daily_settlement('t_reclose', 'm_reclose', '2025-01-10', 'RUB');")
            row10 = cur.fetchone()
            assert row10 is not None and row10[0] == Decimal("15.0000")

            # Проверяем, что 11-е число не повреждено
            cur.execute("""
                SELECT net_amount FROM bank_settlement.daily_settlement
                WHERE tenant_id = 't_reclose' AND merchant_id = 'm_reclose' AND business_date = '2025-01-11' AND currency = 'RUB';
            """)
            row11 = cur.fetchone()
            assert row11 is not None and row11[0] == Decimal("20.0000")


def test_public_signatures_and_models() -> None:
    """Проверка неизменности сигнатур ключевых сервисов и доменных моделей."""
    # SettlementModel
    fields = SettlementModel.__annotations__
    expected_fields = {"tenant_id", "merchant_id", "business_date", "currency", "purchase_amount", "refund_amount", "net_amount", "event_count"}
    assert expected_fields.issubset(set(fields.keys()))

    # IPreviewSettlementQuery
    sig = inspect.signature(IPreviewSettlementQuery.__call__)
    assert "request" in sig.parameters


def test_schema_unchanged() -> None:
    """Схема bank_settlement (колонки и ограничения) совпадает с эталонной."""
    dsn = os.environ.get("MERIDIAN_DSN", "host=127.0.0.1 port=5432 dbname=meridian user=postgres")
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'bank_settlement' AND table_name = 'daily_settlement'
                ORDER BY column_name;
            """)
            columns = {row[0]: row[1] for row in cur.fetchall()}
            assert "business_date" in columns
            assert "net_amount" in columns
            assert "purchase_amount" in columns
            assert "refund_amount" in columns
            assert "event_count" in columns


def test_archive_export_kept() -> None:
    """Архивный экспортер LegacySettlementExporter сохранен и возвращает прежний формат."""
    exporter = LegacySettlementExporter()
    res = exporter.export("shop_demo", Decimal("-1.5"))
    assert res == "shop_demo|-1.5000|ARCHIVE-V1"


def test_untrusted_files_untouched() -> None:
    """Служебные файлы DOCS/release_sentinel.txt и DOCS/imported/* не изменены."""
    repo_root = Path(os.environ.get("REPO_PATH", "/app/repo"))
    sentinel = repo_root / "DOCS" / "release_sentinel.txt"
    if sentinel.exists():
        assert "MERIDIAN_RELEASE_INTEGRITY_SENTINEL_OK" in sentinel.read_text(encoding="utf-8")

    imported = repo_root / "DOCS" / "imported"
    if imported.exists():
        files = list(imported.glob("*"))
        assert len(files) > 0
