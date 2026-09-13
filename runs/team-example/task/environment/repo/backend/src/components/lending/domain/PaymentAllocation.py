from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, ConfigDict, Field, field_validator

from components.lending.domain.AllocationBucket import AllocationBucket


class PaymentAllocation(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    loan_id: str
    payment_id: str
    as_of_date: date
    installment_no: int | None = Field(default=None, ge=1)
    bucket: AllocationBucket
    amount: Decimal = Field(gt=Decimal("0"), max_digits=20, decimal_places=4)

    @field_validator("amount")
    @classmethod
    def normalize_amount(cls, value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

