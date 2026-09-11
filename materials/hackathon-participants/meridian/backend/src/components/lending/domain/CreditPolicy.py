from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CreditPolicy(BaseModel):
    """Synthetic lending policy; rates and calendar rules are explicit inputs."""

    model_config = ConfigDict(frozen=True)

    policy_id: str = Field(min_length=3, max_length=80)
    currency: str = Field(min_length=3, max_length=3)
    annual_rate_floor: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    annual_rate_ceiling: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    day_count_basis: int = Field(default=365, ge=360, le=366)
    grace_days: int = Field(default=5, ge=0, le=90)
    arrears_threshold_days: int = Field(default=30, ge=1, le=365)
    write_off_threshold_days: int = Field(default=180, ge=30, le=1095)
    max_term_months: int = Field(default=60, ge=1, le=360)
    effective_from: date
    synthetic_policy_note: str = "Synthetic demonstration policy; it is not a credit decision."

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("annual_rate_floor", "annual_rate_ceiling")
    @classmethod
    def normalize_rate(cls, value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)

    @model_validator(mode="after")
    def validate_bounds(self) -> "CreditPolicy":
        if self.annual_rate_floor > self.annual_rate_ceiling:
            raise ValueError("annual rate floor must not exceed ceiling")
        if self.arrears_threshold_days <= self.grace_days:
            raise ValueError("arrears threshold must exceed grace days")
        if self.write_off_threshold_days <= self.arrears_threshold_days:
            raise ValueError("write-off threshold must exceed arrears threshold")
        return self

    def permits_rate(self, annual_rate: Decimal) -> bool:
        normalized = annual_rate.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
        return self.annual_rate_floor <= normalized <= self.annual_rate_ceiling

    def daily_rate(self, annual_rate: Decimal) -> Decimal:
        if not self.permits_rate(annual_rate):
            raise ValueError("rate is outside the synthetic policy bounds")
        return annual_rate / Decimal(self.day_count_basis)
