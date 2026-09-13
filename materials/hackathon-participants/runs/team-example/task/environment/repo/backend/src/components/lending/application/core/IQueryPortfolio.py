from abc import ABC, abstractmethod
from datetime import date

from components.lending.domain.CreditPolicy import CreditPolicy
from components.lending.domain.PortfolioSummary import PortfolioSummary


class IQueryPortfolio(ABC):
    @abstractmethod
    async def summary(self, tenant_id: str, as_of_date: date, policy: CreditPolicy) -> PortfolioSummary:
        raise NotImplementedError
