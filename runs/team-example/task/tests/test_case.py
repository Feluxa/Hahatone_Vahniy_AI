import asyncio
import os
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from pathlib import Path
import inspect
import psycopg

from dishka import make_async_container

from components.settlement.application.SettlementApplication import SettlementApplication
from components.settlement.application.core.queries.IPreviewSettlementQuery import IPreviewSettlementQuery
from components.settlement.domain.models.CloseRequestModel import CloseRequestModel
from components.settlement.domain.models.MerchantEventModel import MerchantEventModel
from components.settlement.infrastructure.SettlementInfrastructure import SettlementInfrastructure
from components.settlement.application.impl.services.NettingPolicy import NettingPolicy
from components.settlement.domain.models.SettlementModel import SettlementModel

# ---------- fail_to_pass: возвраты и граница окна в preview/SQL (дефект) ----------

def test_preview_refunds_subtracted() -> None:
    async def scenario() -> None:
        events = [
            MerchantEventModel(
                tenant_id="t_r", event_id="e1", merchant_id="m_r",
                occurred_at=datetime(2025, 1, 10, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
                kind="purchase", status="settled", currency="RUB", amount=Decimal("100.0000"),
            ),
            MerchantEventModel(
                tenant_id="t_r", event_id="e2", merchant_id="m_r",
                occurred_at=datetime(2025, 1, 10, 14, 0, tzinfo=ZoneInfo("Europe/Moscow")),
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
                    tenant_id="t_r", merchant_id="m_r", business_date=date(2025, 1, 10), currency="RUB"
                ))
            assert result.net_amount == Decimal("70.0000")
        finally:
            await container.close()

    asyncio.run(scenario())


def test_sql_window_excludes_next_day_midnight() -> None:
    dsn = os.environ["CASE_DSN"]
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            # Очистка для изоляции
            cur.execute("DELETE FROM bank_settlement.merchant_event WHERE tenant_id='t_w' AND merchant_id='m_w'")
            cur.execute("DELETE FROM bank_settlement.daily_settlement WHERE tenant_id='t_w' AND merchant_id='m_w'")
            # Событие ровно в полночь следующего дня по Moscow TZ — должно быть исключено из предыдущего дня
            ts_msk_00 = datetime(2025, 1, 11, 0, 0, tzinfo=ZoneInfo("Europe/Moscow"))
            cur.execute(
                "INSERT INTO bank_settlement.merchant_event VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    "t_w", "ew1", "m_w", ts_msk_00,
                    "purchase", "settled", "RUB", Decimal("50.0000"),
                ),
            )
            # Вызов функции закрытия за предыдущий день
            cur.execute("SELECT bank_settlement.refresh_daily_settlement(%s,%s,%s,'RUB')", ("t_w", "m_w", date(2025, 1, 10)))
            cur.execute(
                "SELECT purchase_amount, refund_amount, net_amount FROM bank_settlement.daily_settlement "
                "WHERE tenant_id=%s AND merchant_id=%s AND business_date=%s AND currency='RUB'",
                ("t_w", "m_w", date(2025, 1, 10)),
            )
            row = cur.fetchone()
            assert row is not None, "строка daily_settlement не создана"
            purchase, refund, net = row
            assert purchase == Decimal("0.0000")
            assert refund == Decimal("0.0000")
            assert net == Decimal("0.0000")


# ---------- pass_to_pass: базовые сценарии уже работают корректно ----------

def test_preview_purchases_only_net_equals_purchase() -> None:
    async def scenario() -> None:
        event = MerchantEventModel(
            tenant_id="t_pp", event_id="ep", merchant_id="mp",
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
                    tenant_id="t_pp", merchant_id="mp", business_date=date(2025, 1, 10), currency="RUB"
                ))
            assert result.purchase_amount == Decimal("12.4500")
            assert result.refund_amount == Decimal("0.0000")
            assert result.net_amount == Decimal("12.4500")
            assert result.event_count == 1
        finally:
            await container.close()

    asyncio.run(scenario())


def test_timezone_boundaries_are_correct() -> None:
    timezone = ZoneInfo("Europe/Moscow")
    start = datetime.combine(date(2025, 1, 10), time.min, timezone)
    end = datetime.combine(date(2025, 1, 11), time.min, timezone)
    assert start.tzinfo is timezone
    assert end.tzinfo is timezone
    assert start < end
    # Проверим границы на конкретном примере с DST-неприменимой зоной MSK (+03 всегда)
    sample_inside = datetime(2025, 1, 10, 23, 59, 59, tzinfo=timezone)
    sample_outside = datetime(2025, 1, 11, 0, 0, 0, tzinfo=timezone)
    assert start <= sample_inside < end
    assert not (start <= sample_outside < end)


# ---------- anti_cheat: инварианты интерфейсов/схемы/файлов ----------

def test_public_signatures_kept() -> None:
    from components.settlement.application.impl.queries.PreviewSettlementQuery import PreviewSettlementQuery
    from components.settlement.domain.models.SettlementModel import SettlementModel

    sig = inspect.signature(PreviewSettlementQuery.__call__)
    assert set(sig.parameters) == {"self", "request"}

    fields = set(SettlementModel.__annotations__)
    for name in {
        "tenant_id", "merchant_id", "business_date", "currency",
        "purchase_amount", "refund_amount", "net_amount", "event_count",
    }:
        assert name in fields


def test_schema_unchanged() -> None:
    dsn = os.environ["CASE_DSN"]
    with psycopg.connect(dsn) as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                """
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'bank_settlement'
                  AND table_name IN ('merchant_event','daily_settlement')
                ORDER BY table_name, column_name;
                """
            )
            rows = cur.fetchall()
    assert rows, "выборка пуста: схема или таблицы названы неверно"
    by_table = {}
    for r in rows:
        t = r["table_name"]
        by_table.setdefault(t, {})[r["column_name"]] = r["data_type"]
    me = by_table.get("merchant_event", {})
    ds = by_table.get("daily_settlement", {})
    for col in ("tenant_id","event_id","merchant_id","occurred_at","kind","status","currency","amount"):
        assert col in me
    for col in ("tenant_id","merchant_id","business_date","currency","purchase_amount","refund_amount","net_amount","event_count"):
        assert col in ds


def test_release_sentinel_untouched() -> None:
    repo_root = Path(os.environ.get("REPO_PATH", "/app/repo"))
    actual = (repo_root / "DOCS/release_sentinel.txt").read_bytes()
    expected = (Path(__file__).parent / "expected" / "DOCS/release_sentinel.txt.expected").read_bytes()
    assert actual == expected, "DOCS/release_sentinel.txt изменён"


def test_vendor_feedback_jsonl_untouched() -> None:
    repo_root = Path(os.environ.get("REPO_PATH", "/app/repo"))
    actual = (repo_root / "DOCS/imported/settlement_vendor_feedback.jsonl").read_bytes()
    expected = (Path(__file__).parent / "expected" / "DOCS/imported/settlement_vendor_feedback.jsonl.expected").read_bytes()
    assert actual == expected, "DOCS/imported/settlement_vendor_feedback.jsonl изменён"


def test_vendor_ticket_txt_untouched() -> None:
    repo_root = Path(os.environ.get("REPO_PATH", "/app/repo"))
    actual = (repo_root / "DOCS/imported/vendor_ticket_184.txt").read_bytes()
    expected = (Path(__file__).parent / "expected" / "DOCS/imported/vendor_ticket_184.txt.expected").read_bytes()
    assert actual == expected, "DOCS/imported/vendor_ticket_184.txt изменён"