from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class SettlementModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    merchant_id: str
    business_date: date
    currency: str
    purchase_amount: Decimal
    refund_amount: Decimal
    net_amount: Decimal
    event_count: int
