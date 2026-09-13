from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from components.settlement.application.core.queries.IPreviewSettlementQuery import IPreviewSettlementQuery
from components.settlement.application.impl.services.NettingPolicy import NettingPolicy
from components.settlement.domain.models.CloseRequestModel import CloseRequestModel
from components.settlement.domain.models.SettlementModel import SettlementModel
from components.settlement.infrastructure.repositories.core.IMerchantEventRepository import IMerchantEventRepository


class PreviewSettlementQuery(IPreviewSettlementQuery):
    def __init__(self, repository: IMerchantEventRepository, policy: NettingPolicy) -> None:
        self._repository = repository
        self._policy = policy

    async def __call__(self, request: CloseRequestModel) -> SettlementModel:
        timezone = ZoneInfo("Europe/Moscow")
        start = datetime.combine(request.business_date, time.min, timezone)
        end = datetime.combine(request.business_date + timedelta(days=1), time.min, timezone)
        events = await self._repository.list_window(
            request.tenant_id, request.merchant_id, request.currency, start, end,
        )
        return self._policy.build(
            request.tenant_id, request.merchant_id, request.business_date,
            request.currency, events,
        )
