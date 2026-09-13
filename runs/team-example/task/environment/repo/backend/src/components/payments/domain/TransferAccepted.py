from datetime import datetime

from pydantic import BaseModel, ConfigDict

from components.payments.domain.Money import Money


class TransferAccepted(BaseModel):
    """Event emitted after an accepted transfer is durably committed."""

    model_config = ConfigDict(frozen=True)

    tenant_id: str
    transfer_id: str
    source_account_id: str
    destination_account_id: str
    amount: Money
    occurred_at: datetime
