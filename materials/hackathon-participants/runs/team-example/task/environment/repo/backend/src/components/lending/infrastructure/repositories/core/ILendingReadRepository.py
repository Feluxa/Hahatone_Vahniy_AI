from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal

from components.lending.domain.Installment import Installment
from components.lending.domain.EarlyFunds import EarlyFunds
from components.lending.domain.Loan import Loan


class ILendingReadRepository(ABC):
    @abstractmethod
    async def get_loan(self, tenant_id: str, loan_id: str) -> Loan | None:
        raise NotImplementedError

    @abstractmethod
    async def list_loans(self, tenant_id: str) -> tuple[Loan, ...]:
        raise NotImplementedError

    @abstractmethod
    async def list_installments(self, tenant_id: str, loan_id: str) -> tuple[Installment, ...]:
        raise NotImplementedError

    @abstractmethod
    async def get_early_funds(self, tenant_id: str, loan_id: str) -> Decimal:
        raise NotImplementedError

    @abstractmethod
    async def find_early_funds(self, tenant_id: str, loan_id: str) -> EarlyFunds | None:
        raise NotImplementedError

    @abstractmethod
    async def exists_payment(self, tenant_id: str, loan_id: str, payment_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def list_due_before(self, tenant_id: str, as_of_date: date) -> tuple[Installment, ...]:
        raise NotImplementedError
