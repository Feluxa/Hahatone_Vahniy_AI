from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PortfolioSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    as_of_date: date
    loan_count: int = Field(ge=0)
    active_loan_count: int = Field(ge=0)
    delinquent_loan_count: int = Field(ge=0)
    original_principal: Decimal = Field(ge=Decimal("0"))
    outstanding_principal: Decimal = Field(ge=Decimal("0"))
    overdue_amount: Decimal = Field(ge=Decimal("0"))
    early_funds_balance: Decimal = Field(ge=Decimal("0"))
