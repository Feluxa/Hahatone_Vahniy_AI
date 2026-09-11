import asyncio
from datetime import date, datetime
from decimal import Decimal

from dishka import make_async_container

from components.settlement.application.SettlementApplication import SettlementApplication
from components.settlement.application.core.queries.IPreviewSettlementQuery import IPreviewSettlementQuery
from components.settlement.domain.models.CloseRequestModel import CloseRequestModel
from components.settlement.domain.models.MerchantEventModel import MerchantEventModel
from components.settlement.infrastructure.SettlementInfrastructure import SettlementInfrastructure
from components.settlement.infrastructure.legacy.LegacySettlementExporter import LegacySettlementExporter


def test_preview_purchases_and_real_di_resolution() -> None:
    async def scenario() -> None:
        event = MerchantEventModel(
            tenant_id="tenant_demo", event_id="event_demo", merchant_id="shop_demo",
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
                    tenant_id="tenant_demo", merchant_id="shop_demo",
                    business_date=date(2025, 1, 10), currency="RUB",
                ))
            assert result.net_amount == Decimal("12.4500")
            assert result.event_count == 1
        finally:
            await container.close()
    asyncio.run(scenario())


def test_archive_export_is_still_required() -> None:
    assert LegacySettlementExporter().export("shop_demo", Decimal("-1.5")) == "shop_demo|-1.5000|ARCHIVE-V1"
