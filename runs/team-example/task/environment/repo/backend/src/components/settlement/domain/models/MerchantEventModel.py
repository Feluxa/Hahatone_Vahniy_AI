from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MerchantEventModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    event_id: str
    merchant_id: str
    occurred_at: datetime
    kind: Literal["purchase", "refund"]
    status: Literal["settled", "pending", "void"]
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=4)

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("occurred_at must be timezone aware")
        return value
