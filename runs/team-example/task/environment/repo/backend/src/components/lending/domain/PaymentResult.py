from decimal import Decimal

from pydantic import BaseModel, ConfigDict, model_validator

from components.lending.domain.PaymentAllocation import PaymentAllocation


class PaymentResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    loan_id: str
    payment_id: str
    received_amount: Decimal
    allocated_amount: Decimal
    unapplied_early_funds: Decimal
    allocations: tuple[PaymentAllocation, ...]

    @model_validator(mode="after")
    def reconcile(self) -> "PaymentResult":
        if self.allocated_amount + self.unapplied_early_funds != self.received_amount:
            raise ValueError("payment result must reconcile to received amount")
        return self
