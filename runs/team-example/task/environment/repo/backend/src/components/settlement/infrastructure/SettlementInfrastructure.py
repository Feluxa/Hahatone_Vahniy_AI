from dishka import Provider, Scope

from components.settlement.domain.models.MerchantEventModel import MerchantEventModel
from components.settlement.infrastructure.repositories.core.IMerchantEventRepository import IMerchantEventRepository
from components.settlement.infrastructure.repositories.impl.MemoryMerchantEventRepository import MemoryMerchantEventRepository


class SettlementInfrastructure:
    def __init__(self, events: list[MerchantEventModel]) -> None:
        self._events = list(events)

    def __call__(self) -> Provider:
        provider = Provider(scope=Scope.REQUEST)
        provider.provide(self.repository, provides=IMerchantEventRepository)
        return provider

    def repository(self) -> IMerchantEventRepository:
        return MemoryMerchantEventRepository(self._events)
