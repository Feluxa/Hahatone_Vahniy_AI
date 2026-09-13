from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from components.lending.domain.EarlyFunds import EarlyFunds
from components.lending.domain.Installment import Installment
from components.lending.domain.Loan import Loan
from components.lending.domain.PaymentResult import PaymentResult
from components.lending.infrastructure.repositories.core.ILendingReadRepository import ILendingReadRepository


class MemoryLendingReadRepository(ILendingReadRepository):
    """Reference adapter deliberately scoped to one process and injected store."""

    # TODO(meridian-184): add a PostgreSQL read adapter after the shared loan DDL is available.

    def __init__(self, store: dict[str, dict[tuple[str, ...], BaseModel]]) -> None:
        self._store = store

    async def get_loan(self, tenant_id: str, loan_id: str) -> Loan | None:
        item = self._store.get("loans", {}).get((tenant_id, loan_id))
        return item.model_copy(deep=True) if isinstance(item, Loan) else None

    async def list_loans(self, tenant_id: str) -> tuple[Loan, ...]:
        rows = [
            item.model_copy(deep=True)
            for item in self._store.get("loans", {}).values()
            if isinstance(item, Loan) and item.tenant_id == tenant_id
        ]
        return tuple(sorted(rows, key=lambda row: row.loan_id))

    async def list_installments(self, tenant_id: str, loan_id: str) -> tuple[Installment, ...]:
        rows = [
            item.model_copy(deep=True)
            for item in self._store.get("installments", {}).values()
            if isinstance(item, Installment) and item.tenant_id == tenant_id and item.loan_id == loan_id
        ]
        return tuple(sorted(rows, key=lambda row: row.installment_no))

    async def get_early_funds(self, tenant_id: str, loan_id: str) -> Decimal:
        item = await self.find_early_funds(tenant_id, loan_id)
        if isinstance(item, EarlyFunds):
            return item.balance
        return Decimal("0.0000")

    async def find_early_funds(self, tenant_id: str, loan_id: str) -> EarlyFunds | None:
        item = self._store.get("early_funds", {}).get((tenant_id, loan_id))
        return item.model_copy(deep=True) if isinstance(item, EarlyFunds) else None

    async def exists_payment(self, tenant_id: str, loan_id: str, payment_id: str) -> bool:
        item = self._store.get("payments", {}).get((tenant_id, loan_id, payment_id))
        return isinstance(item, PaymentResult)

    async def list_due_before(self, tenant_id: str, as_of_date: date) -> tuple[Installment, ...]:
        rows = [
            item.model_copy(deep=True)
            for item in self._store.get("installments", {}).values()
            if isinstance(item, Installment) and item.tenant_id == tenant_id and item.due_date <= as_of_date
        ]
        return tuple(sorted(rows, key=lambda row: (row.due_date, row.loan_id, row.installment_no)))
