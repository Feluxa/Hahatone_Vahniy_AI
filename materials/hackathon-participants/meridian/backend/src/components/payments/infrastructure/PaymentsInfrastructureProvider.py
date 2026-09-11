from dishka import Provider, Scope, provide

from components.payments.infrastructure.repositories.core.ITransferIntentReadRepository import (
    ITransferIntentReadRepository,
)
from components.payments.infrastructure.repositories.core.ITransferIntentWritePort import (
    ITransferIntentWritePort,
)
from components.payments.infrastructure.repositories.impl.MemoryPaymentStore import MemoryPaymentStore
from components.payments.infrastructure.repositories.impl.MemoryTransferIntentRepository import (
    MemoryTransferIntentRepository,
)


class PaymentsInfrastructureProvider(Provider):
    """APP-scoped store and repository bindings for the local payments demo."""

    @provide(scope=Scope.APP)
    def payment_store(self) -> MemoryPaymentStore:
        return MemoryPaymentStore()

    @provide(scope=Scope.APP)
    def memory_repository(self, store: MemoryPaymentStore) -> MemoryTransferIntentRepository:
        return MemoryTransferIntentRepository(store)

    @provide(provides=ITransferIntentReadRepository, scope=Scope.APP)
    def read_repository(self, repository: MemoryTransferIntentRepository) -> ITransferIntentReadRepository:
        return repository

    @provide(provides=ITransferIntentWritePort, scope=Scope.APP)
    def write_repository(self, repository: MemoryTransferIntentRepository) -> ITransferIntentWritePort:
        return repository
