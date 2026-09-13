from dishka import Provider, Scope, provide
from pydantic import BaseModel

from components.lending.application.impl.DelinquencyService import DelinquencyService
from components.lending.application.impl.LoanService import LoanService
from components.lending.application.impl.PaymentAllocationService import PaymentAllocationService
from components.lending.application.impl.PortfolioQueryService import PortfolioQueryService
from components.lending.application.impl.RestructuringPreviewService import RestructuringPreviewService
from components.lending.application.impl.ScheduleService import ScheduleService
from components.lending.infrastructure.repositories.core.ILendingReadRepository import ILendingReadRepository
from components.lending.infrastructure.uow.LendingMemoryUnitOfWork import LendingMemoryUnitOfWork
from system.uow.IUnitOfWork import IUnitOfWork


class LendingRequestProvider(Provider):
    """Request-scoped UoW and stateless lending service bindings."""

    @provide(scope=Scope.REQUEST)
    def unit_of_work(self, memory_store: dict[str, dict[tuple[str, ...], BaseModel]]) -> LendingMemoryUnitOfWork:
        return LendingMemoryUnitOfWork(memory_store)

    @provide(provides=IUnitOfWork, scope=Scope.REQUEST)
    def interface_unit_of_work(self, unit_of_work: LendingMemoryUnitOfWork) -> IUnitOfWork:
        return unit_of_work

    @provide(scope=Scope.REQUEST)
    def schedule_service(self, unit_of_work: IUnitOfWork) -> ScheduleService:
        return ScheduleService(unit_of_work)

    @provide(scope=Scope.REQUEST)
    def delinquency_service(self, repository: ILendingReadRepository, unit_of_work: IUnitOfWork) -> DelinquencyService:
        return DelinquencyService(repository, unit_of_work)

    @provide(scope=Scope.REQUEST)
    def payment_service(self, repository: ILendingReadRepository, unit_of_work: IUnitOfWork) -> PaymentAllocationService:
        return PaymentAllocationService(repository, unit_of_work)

    @provide(scope=Scope.REQUEST)
    def portfolio_service(self, repository: ILendingReadRepository, delinquency_service: DelinquencyService) -> PortfolioQueryService:
        return PortfolioQueryService(repository, delinquency_service)

    @provide(scope=Scope.REQUEST)
    def restructuring_service(self, repository: ILendingReadRepository, schedule_service: ScheduleService, delinquency_service: DelinquencyService) -> RestructuringPreviewService:
        return RestructuringPreviewService(repository, schedule_service, delinquency_service)

    @provide(scope=Scope.REQUEST)
    def loan_service(self, repository: ILendingReadRepository, unit_of_work: IUnitOfWork, schedule_service: ScheduleService) -> LoanService:
        return LoanService(repository, unit_of_work, schedule_service)
