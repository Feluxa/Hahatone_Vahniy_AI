from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class RestructuringPreview(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    loan_id: str
    requested_on: date
    proposed_maturity_date: date
    proposed_term_months: int = Field(ge=1, le=360)
    outstanding_principal: Decimal = Field(ge=Decimal("0"))
    overdue_amount: Decimal = Field(ge=Decimal("0"))
    proposed_periodic_payment: Decimal = Field(ge=Decimal("0"))
    eligible: bool
    reasons: tuple[str, ...]
    policy_id: str
