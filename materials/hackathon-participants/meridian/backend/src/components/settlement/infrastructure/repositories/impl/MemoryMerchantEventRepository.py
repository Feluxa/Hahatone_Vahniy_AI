from datetime import datetime

from components.settlement.domain.models.MerchantEventModel import MerchantEventModel
from components.settlement.infrastructure.repositories.core.IMerchantEventRepository import IMerchantEventRepository


class MemoryMerchantEventRepository(IMerchantEventRepository):
    def __init__(self, events: list[MerchantEventModel]) -> None:
        self._events = tuple(events)

    async def list_window(
        self, tenant_id: str, merchant_id: str, currency: str,
        start: datetime, end: datetime,
    ) -> list[MerchantEventModel]:
        return [
            event for event in self._events
            if event.tenant_id == tenant_id and event.merchant_id == merchant_id
            and event.currency == currency and start <= event.occurred_at < end
        ]
