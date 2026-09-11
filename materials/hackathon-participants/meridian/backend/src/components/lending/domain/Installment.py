from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Installment(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str = Field(min_length=1, max_length=80)
    loan_id: str = Field(min_length=1, max_length=100)
    installment_no: int = Field(ge=1, le=360)
    due_date: date
    principal_due: Decimal = Field(ge=Decimal("0"), max_digits=20, decimal_places=4)
    interest_due: Decimal = Field(ge=Decimal("0"), max_digits=20, decimal_places=4)
    principal_paid: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), max_digits=20, decimal_places=4)
    interest_paid: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), max_digits=20, decimal_places=4)

    @field_validator("principal_due", "interest_due", "principal_paid", "interest_paid")
    @classmethod
    def normalize_money(cls, value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    @model_validator(mode="after")
    def paid_cannot_exceed_due(self) -> "Installment":
        if self.principal_paid > self.principal_due:
            raise ValueError("principal paid cannot exceed principal due")
        if self.interest_paid > self.interest_due:
            raise ValueError("interest paid cannot exceed interest due")
        if self.principal_due + self.interest_due <= Decimal("0"):
            raise ValueError("installment must have a positive due amount")
        return self

    @property
    def total_due(self) -> Decimal:
        return self.principal_due + self.interest_due

    @property
    def total_paid(self) -> Decimal:
        return self.principal_paid + self.interest_paid

    @property
    def outstanding_interest(self) -> Decimal:
        return self.interest_due - self.interest_paid

    @property
    def outstanding_principal(self) -> Decimal:
        return self.principal_due - self.principal_paid

    @property
    def outstanding_total(self) -> Decimal:
        return self.outstanding_interest + self.outstanding_principal

    @property
    def is_settled(self) -> bool:
        return self.outstanding_total == Decimal("0")

    def apply(self, interest: Decimal, principal: Decimal) -> "Installment":
        if interest < 0 or principal < 0:
            raise ValueError("allocation values must be non-negative")
        return self.model_copy(
            update={
                "interest_paid": self.interest_paid + interest,
                "principal_paid": self.principal_paid + principal,
            }
        )
