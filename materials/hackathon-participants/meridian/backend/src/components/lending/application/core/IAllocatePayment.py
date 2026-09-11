from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal

from components.lending.domain.PaymentResult import PaymentResult


class IAllocatePayment(ABC):
    @abstractmethod
    async def allocate(self, tenant_id: str, loan_id: str, payment_id: str, amount: Decimal, received_on: date) -> PaymentResult:
        raise NotImplementedError
