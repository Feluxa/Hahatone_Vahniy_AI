from datetime import date
from decimal import Decimal

from components.lending.application.impl.DelinquencyService import DelinquencyService
from components.lending.application.core.IQueryPortfolio import IQueryPortfolio
from components.lending.domain.CreditPolicy import CreditPolicy
from components.lending.domain.Loan import LoanStatus
from components.lending.domain.LoanPortfolioRow import LoanPortfolioRow
from components.lending.domain.PortfolioSummary import PortfolioSummary
from components.lending.infrastructure.repositories.core.ILendingReadRepository import ILendingReadRepository


class PortfolioQueryService(IQueryPortfolio):
    def __init__(self, repository: ILendingReadRepository, delinquency_service: DelinquencyService) -> None:
        self._repository = repository
        self._delinquency_service = delinquency_service

    async def summary(self, tenant_id: str, as_of_date: date, policy: CreditPolicy) -> PortfolioSummary:
        rows = await self.rows(tenant_id, as_of_date, policy)
        loans = await self._repository.list_loans(tenant_id)
        early = Decimal("0")
        for loan in loans:
            early += await self._repository.get_early_funds(tenant_id, loan.loan_id)
        return PortfolioSummary(tenant_id=tenant_id, as_of_date=as_of_date, loan_count=len(loans), active_loan_count=sum(loan.status in {LoanStatus.ACTIVE, LoanStatus.DELINQUENT, LoanStatus.RESTRUCTURED} for loan in loans), delinquent_loan_count=sum(row.days_past_due > policy.grace_days for row in rows), original_principal=sum((loan.principal for loan in loans), Decimal("0")), outstanding_principal=sum((row.outstanding_principal for row in rows), Decimal("0")), overdue_amount=sum((row.overdue_amount for row in rows), Decimal("0")), early_funds_balance=early)

    async def rows(self, tenant_id: str, as_of_date: date, policy: CreditPolicy) -> tuple[LoanPortfolioRow, ...]:
        loans = await self._repository.list_loans(tenant_id)
        result: list[LoanPortfolioRow] = []
        for loan in loans:
            installments = await self._repository.list_installments(tenant_id, loan.loan_id)
            delinquency = await self._delinquency_service.assess(tenant_id, loan.loan_id, as_of_date, policy)
            result.append(LoanPortfolioRow(tenant_id=tenant_id, loan_id=loan.loan_id, customer_id=loan.customer_id, status=loan.status.value, currency=loan.currency, outstanding_principal=sum((row.outstanding_principal for row in installments), Decimal("0")), overdue_amount=delinquency.overdue_amount, days_past_due=delinquency.days_past_due))
        return tuple(sorted(result, key=lambda row: row.loan_id))
