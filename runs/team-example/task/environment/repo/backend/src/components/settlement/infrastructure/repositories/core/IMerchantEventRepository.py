from abc import ABC, abstractmethod
from datetime import datetime

from components.settlement.domain.models.MerchantEventModel import MerchantEventModel


class IMerchantEventRepository(ABC):
    @abstractmethod
    async def list_window(
        self, tenant_id: str, merchant_id: str, currency: str,
        start: datetime, end: datetime,
    ) -> list[MerchantEventModel]:
        raise NotImplementedError
