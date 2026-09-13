from abc import ABC, abstractmethod

from components.lending.domain.CreditPolicy import CreditPolicy
from components.lending.domain.Loan import Loan


class IOpenLoan(ABC):
    @abstractmethod
    async def open(self, loan: Loan, policy: CreditPolicy) -> Loan:
        raise NotImplementedError
