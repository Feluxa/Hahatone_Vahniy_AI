from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TransferReversed(BaseModel):
    """Event emitted after a reversal state is durably committed."""

    model_config = ConfigDict(frozen=True)

    tenant_id: str
    transfer_id: str
    reason: str
    occurred_at: datetime
