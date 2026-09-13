from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class LoanPortfolioRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    loan_id: str
    customer_id: str
    status: str
    currency: str
    outstanding_principal: Decimal
    overdue_amount: Decimal
    days_past_due: int
