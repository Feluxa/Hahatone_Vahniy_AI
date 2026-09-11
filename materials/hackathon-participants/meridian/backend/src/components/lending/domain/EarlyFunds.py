from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EarlyFunds(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    loan_id: str
    balance: Decimal = Field(ge=Decimal("0"), max_digits=20, decimal_places=4)

    @field_validator("balance")
    @classmethod
    def normalize_balance(cls, value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
