from calendar import monthrange
from datetime import date
from decimal import Decimal

from components.lending.application.impl.DelinquencyService import DelinquencyService
from components.lending.application.impl.ScheduleService import ScheduleService
from components.lending.domain.CreditPolicy import CreditPolicy
from components.lending.domain.RestructuringPreview import RestructuringPreview
from components.lending.infrastructure.repositories.core.ILendingReadRepository import ILendingReadRepository


class RestructuringPreviewService:
    def __init__(self, repository: ILendingReadRepository, schedule_service: ScheduleService, delinquency_service: DelinquencyService) -> None:
        self._repository = repository
        self._schedule_service = schedule_service
        self._delinquency_service = delinquency_service

    async def preview(self, tenant_id: str, loan_id: str, requested_on: date, extension_months: int, policy: CreditPolicy) -> RestructuringPreview:
        loan = await self._repository.get_loan(tenant_id, loan_id)
        if loan is None:
            raise LookupError("loan does not exist in tenant")
        installments = await self._repository.list_installments(tenant_id, loan_id)
        delinquency = await self._delinquency_service.assess(tenant_id, loan_id, requested_on, policy)
        remaining_principal = sum((row.outstanding_principal for row in installments), Decimal("0"))
        proposed_term = loan.term_months + extension_months
        reasons: list[str] = []
        if extension_months < 1:
            reasons.append("extension must include at least one month")
        if proposed_term > policy.max_term_months:
            reasons.append("proposed term exceeds policy maximum")
        if loan.restructuring_count >= 2:
            reasons.append("synthetic policy permits no more than two restructurings")
        if remaining_principal == 0:
            reasons.append("loan has no principal remaining")
        proposed_maturity = self._add_months(loan.maturity_date, max(extension_months, 0))
        payment = self._schedule_service.quote_periodic_payment(remaining_principal, loan.annual_rate, max(proposed_term, 1)) if remaining_principal > 0 else Decimal("0")
        return RestructuringPreview(tenant_id=tenant_id, loan_id=loan_id, requested_on=requested_on, proposed_maturity_date=proposed_maturity, proposed_term_months=proposed_term, outstanding_principal=remaining_principal, overdue_amount=delinquency.overdue_amount, proposed_periodic_payment=payment, eligible=not reasons, reasons=tuple(reasons), policy_id=policy.policy_id)

    def _add_months(self, initial: date, months: int) -> date:
        absolute_month = initial.month - 1 + months
        year = initial.year + absolute_month // 12
        month = absolute_month % 12 + 1
        return date(year, month, min(initial.day, monthrange(year, month)[1]))
