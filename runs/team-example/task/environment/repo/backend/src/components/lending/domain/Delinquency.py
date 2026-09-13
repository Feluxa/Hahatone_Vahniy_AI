from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from components.lending.domain.DelinquencyBand import DelinquencyBand


class DelinquencySnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    loan_id: str
    as_of_date: date
    days_past_due: int = Field(ge=0)
    overdue_amount: Decimal = Field(ge=Decimal("0"))
    oldest_unpaid_due_date: date | None = None
    band: DelinquencyBand
    recommended_status: str

    @property
    def is_delinquent(self) -> bool:
        return self.band in {
            DelinquencyBand.EARLY_ARREARS,
            DelinquencyBand.LATE_ARREARS,
            DelinquencyBand.DEFAULT,
        }
