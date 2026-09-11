from datetime import date
from decimal import Decimal

from components.lending.domain.CreditPolicy import CreditPolicy
from components.lending.domain.Delinquency import DelinquencySnapshot
from components.lending.domain.DelinquencyBand import DelinquencyBand
from components.lending.domain.Installment import Installment
from components.lending.domain.Loan import LoanStatus
from components.lending.infrastructure.repositories.core.ILendingReadRepository import ILendingReadRepository
from system.uow.IUnitOfWork import IUnitOfWork


class DelinquencyService:
    def __init__(self, repository: ILendingReadRepository, unit_of_work: IUnitOfWork) -> None:
        self._repository = repository
        self._unit_of_work = unit_of_work

    async def assess(self, tenant_id: str, loan_id: str, as_of_date: date, policy: CreditPolicy, persist_status: bool = False) -> DelinquencySnapshot:
        loan = await self._repository.get_loan(tenant_id, loan_id)
        if loan is None:
            raise LookupError("loan does not exist in tenant")
        installments = await self._repository.list_installments(tenant_id, loan_id)
        overdue = tuple(row for row in installments if row.due_date < as_of_date and not row.is_settled)
        oldest = min((row.due_date for row in overdue), default=None)
        days = (as_of_date - oldest).days if oldest else 0
        amount = sum((row.outstanding_total for row in overdue), Decimal("0"))
        band = self._band(days, policy)
        snapshot = DelinquencySnapshot(tenant_id=tenant_id, loan_id=loan_id, as_of_date=as_of_date, days_past_due=days, overdue_amount=amount, oldest_unpaid_due_date=oldest, band=band, recommended_status=self._status(band))
        if persist_status:
            status = LoanStatus(snapshot.recommended_status)
            if loan.status != status and loan.status not in {LoanStatus.CLOSED, LoanStatus.WRITTEN_OFF}:
                self._unit_of_work.register_dirty(loan.with_status(status))
                await self._unit_of_work.commit()
        return snapshot

    def _band(self, days: int, policy: CreditPolicy) -> DelinquencyBand:
        if days == 0:
            return DelinquencyBand.CURRENT
        if days <= policy.grace_days:
            return DelinquencyBand.GRACE
        if days < policy.arrears_threshold_days:
            return DelinquencyBand.EARLY_ARREARS
        if days < policy.write_off_threshold_days:
            return DelinquencyBand.LATE_ARREARS
        return DelinquencyBand.DEFAULT

    def _status(self, band: DelinquencyBand) -> str:
        if band == DelinquencyBand.DEFAULT:
            return LoanStatus.WRITTEN_OFF.value
        if band in {DelinquencyBand.EARLY_ARREARS, DelinquencyBand.LATE_ARREARS}:
            return LoanStatus.DELINQUENT.value
        return LoanStatus.ACTIVE.value
