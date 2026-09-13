from datetime import datetime

from pydantic import BaseModel, Field

from components.payments.domain.TransferState import TransferState


class ListTransfersRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=80)
    limit: int = Field(default=50, ge=1, le=200)
    cursor: datetime | None = None
    state: TransferState | None = None
