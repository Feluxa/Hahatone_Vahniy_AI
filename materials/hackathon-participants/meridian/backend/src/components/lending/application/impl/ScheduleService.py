from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from components.lending.domain.CreditPolicy import CreditPolicy
from components.lending.domain.Installment import Installment
from components.lending.domain.Loan import Loan
from system.uow.IUnitOfWork import IUnitOfWork


class ScheduleService:
    def __init__(self, unit_of_work: IUnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    async def create_schedule(self, loan: Loan, policy: CreditPolicy) -> tuple[Installment, ...]:
        installments = self.build_schedule(loan, policy)
        for installment in installments:
            self._unit_of_work.register_new(installment)
        await self._unit_of_work.commit()
        return installments

    def quote_periodic_payment(self, principal: Decimal, annual_rate: Decimal, term_months: int) -> Decimal:
        if principal <= 0 or term_months <= 0:
            raise ValueError("principal and term must be positive")
        rate = annual_rate / Decimal("12")
        if rate == 0:
            return self._money(principal / Decimal(term_months))
        factor = (Decimal("1") + rate) ** term_months
        return self._money(principal * rate * factor / (factor - Decimal("1")))

    def build_schedule(self, loan: Loan, policy: CreditPolicy) -> tuple[Installment, ...]:
        self._validate_schedule_inputs(loan, policy)
        periodic_payment = self.quote_periodic_payment(loan.principal, loan.annual_rate, loan.term_months)
        remaining = loan.principal
        due_date = loan.opened_on
        installments: list[Installment] = []
        monthly_rate = loan.annual_rate / Decimal("12")
        for number in range(1, loan.term_months + 1):
            due_date = self._add_months(loan.opened_on, number)
            interest = self._money(remaining * monthly_rate)
            principal = self._money(periodic_payment - interest)
            if number == loan.term_months or principal > remaining:
                principal = remaining
            if principal <= 0:
                raise ValueError("payment does not amortize the loan")
            installments.append(
                Installment(
                    tenant_id=loan.tenant_id,
                    loan_id=loan.loan_id,
                    installment_no=number,
                    due_date=due_date,
                    principal_due=principal,
                    interest_due=interest,
                )
            )
            remaining = self._money(remaining - principal)
        return tuple(installments)

    def _validate_schedule_inputs(self, loan: Loan, policy: CreditPolicy) -> None:
        if loan.currency != policy.currency:
            raise ValueError("loan currency must match policy currency")
        if loan.term_months > policy.max_term_months:
            raise ValueError("loan term exceeds policy maximum")
        if not policy.permits_rate(loan.annual_rate):
            raise ValueError("loan rate is outside policy bounds")

    def _add_months(self, initial: date, months: int) -> date:
        absolute_month = initial.month - 1 + months
        year = initial.year + absolute_month // 12
        month = absolute_month % 12 + 1
        return date(year, month, min(initial.day, monthrange(year, month)[1]))

    def _money(self, amount: Decimal) -> Decimal:
        return amount.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
