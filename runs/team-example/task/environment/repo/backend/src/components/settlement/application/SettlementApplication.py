from dishka import Provider, Scope

from components.settlement.application.core.queries.IPreviewSettlementQuery import IPreviewSettlementQuery
from components.settlement.application.impl.queries.PreviewSettlementQuery import PreviewSettlementQuery
from components.settlement.application.impl.services.NettingPolicy import NettingPolicy


class SettlementApplication:
    def __call__(self) -> Provider:
        provider = Provider(scope=Scope.REQUEST)
        provider.provide(NettingPolicy)
        provider.provide(PreviewSettlementQuery, provides=IPreviewSettlementQuery)
        return provider
