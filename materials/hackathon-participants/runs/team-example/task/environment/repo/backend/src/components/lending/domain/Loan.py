from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from components.lending.domain.LoanStatus import LoanStatus


class Loan(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str = Field(min_length=1, max_length=80)
    loan_id: str = Field(min_length=1, max_length=100)
    customer_id: str = Field(min_length=1, max_length=100)
    account_id: str = Field(min_length=1, max_length=100)
    currency: str = Field(min_length=3, max_length=3)
    principal: Decimal = Field(gt=Decimal("0"), max_digits=20, decimal_places=4)
    annual_rate: Decimal = Field(ge=Decimal("0"), le=Decimal("1"), max_digits=12, decimal_places=8)
    opened_on: date
    maturity_date: date
    term_months: int = Field(ge=1, le=360)
    status: LoanStatus = LoanStatus.ACTIVE
    restructuring_count: int = Field(default=0, ge=0, le=10)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("principal")
    @classmethod
    def money_precision(cls, value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    @field_validator("annual_rate")
    @classmethod
    def rate_precision(cls, value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)

    @model_validator(mode="after")
    def validate_dates(self) -> "Loan":
        if self.maturity_date <= self.opened_on:
            raise ValueError("maturity date must be after opening date")
        return self

    @property
    def identity(self) -> tuple[str, str]:
        return self.tenant_id, self.loan_id

    def can_accept_payment(self) -> bool:
        return self.status in {LoanStatus.ACTIVE, LoanStatus.DELINQUENT, LoanStatus.RESTRUCTURED}

    def with_status(self, status: LoanStatus) -> "Loan":
        return self.model_copy(update={"status": status})

    def with_restructure(self, maturity_date: date, term_months: int) -> "Loan":
        return self.model_copy(
            update={
                "maturity_date": maturity_date,
                "term_months": term_months,
                "status": LoanStatus.RESTRUCTURED,
                "restructuring_count": self.restructuring_count + 1,
            }
        )
