from components.lending.domain.CreditPolicy import CreditPolicy
from components.lending.domain.Loan import Loan
from components.lending.application.core.IOpenLoan import IOpenLoan
from components.lending.application.impl.ScheduleService import ScheduleService
from components.lending.infrastructure.repositories.core.ILendingReadRepository import ILendingReadRepository
from system.uow.IUnitOfWork import IUnitOfWork


class LoanService(IOpenLoan):
    def __init__(self, repository: ILendingReadRepository, unit_of_work: IUnitOfWork, schedule_service: ScheduleService) -> None:
        self._repository = repository
        self._unit_of_work = unit_of_work
        self._schedule_service = schedule_service

    async def open(self, loan: Loan, policy: CreditPolicy) -> Loan:
        existing = await self._repository.get_loan(loan.tenant_id, loan.loan_id)
        if existing is not None:
            raise ValueError("loan id is already present in this tenant")
        if not policy.permits_rate(loan.annual_rate):
            raise ValueError("loan rate violates policy")
        schedule = self._schedule_service.build_schedule(loan, policy)
        self._unit_of_work.register_new(loan)
        for installment in schedule:
            self._unit_of_work.register_new(installment)
        await self._unit_of_work.commit()
        return loan
