from dishka import Provider, Scope, provide

from common.events.IEventBus import IEventBus

from components.payments.application.core.IEventStagingUnitOfWork import IEventStagingUnitOfWork
from components.payments.application.core.IGetTransferQuery import IGetTransferQuery
from components.payments.application.core.IListTransfersQuery import IListTransfersQuery
from components.payments.application.core.IReverseTransferCommand import IReverseTransferCommand
from components.payments.application.core.ISubmitTransferCommand import ISubmitTransferCommand
from components.payments.application.core.IValidateBatchCommand import IValidateBatchCommand
from components.payments.application.impl.GetTransferQuery import GetTransferQuery
from components.payments.application.impl.ListTransfersQuery import ListTransfersQuery
from components.payments.application.impl.ReverseTransferCommand import ReverseTransferCommand
from components.payments.application.impl.SubmitTransferCommand import SubmitTransferCommand
from components.payments.application.impl.ValidateBatchCommand import ValidateBatchCommand
from components.payments.infrastructure.repositories.core.ITransferIntentReadRepository import (
    ITransferIntentReadRepository,
)
from components.payments.infrastructure.repositories.core.ITransferIntentWritePort import (
    ITransferIntentWritePort,
)
from components.payments.infrastructure.repositories.impl.MemoryPaymentStore import MemoryPaymentStore
from components.payments.infrastructure.uow.MemoryPaymentsUnitOfWork import MemoryPaymentsUnitOfWork


class PaymentsApplicationProvider(Provider):
    """REQUEST-scoped payments UoW and application command/query bindings."""

    @provide(scope=Scope.REQUEST)
    def payments_uow(
        self,
        store: MemoryPaymentStore,
        write_port: ITransferIntentWritePort,
        event_bus: IEventBus,
    ) -> MemoryPaymentsUnitOfWork:
        return MemoryPaymentsUnitOfWork(store, write_port, event_bus)

    @provide(provides=IEventStagingUnitOfWork, scope=Scope.REQUEST)
    def event_staging_uow(self, unit_of_work: MemoryPaymentsUnitOfWork) -> IEventStagingUnitOfWork:
        return unit_of_work

    @provide(provides=ISubmitTransferCommand, scope=Scope.REQUEST)
    def submit_transfer(
        self,
        repository: ITransferIntentReadRepository,
        unit_of_work: IEventStagingUnitOfWork,
    ) -> ISubmitTransferCommand:
        return SubmitTransferCommand(repository, unit_of_work)

    @provide(provides=IReverseTransferCommand, scope=Scope.REQUEST)
    def reverse_transfer(
        self,
        repository: ITransferIntentReadRepository,
        unit_of_work: IEventStagingUnitOfWork,
    ) -> IReverseTransferCommand:
        return ReverseTransferCommand(repository, unit_of_work)

    @provide(provides=IGetTransferQuery, scope=Scope.REQUEST)
    def get_transfer(self, repository: ITransferIntentReadRepository) -> IGetTransferQuery:
        return GetTransferQuery(repository)

    @provide(provides=IListTransfersQuery, scope=Scope.REQUEST)
    def list_transfers(self, repository: ITransferIntentReadRepository) -> IListTransfersQuery:
        return ListTransfersQuery(repository)

    @provide(provides=IValidateBatchCommand, scope=Scope.REQUEST)
    def validate_batch(self) -> IValidateBatchCommand:
        return ValidateBatchCommand()
