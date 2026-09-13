from components.settlement.domain.models.CloseRequestModel import CloseRequestModel
from components.settlement.domain.models.SettlementModel import SettlementModel


class IPreviewSettlementQuery:
    async def __call__(self, request: CloseRequestModel) -> SettlementModel:
        raise NotImplementedError
