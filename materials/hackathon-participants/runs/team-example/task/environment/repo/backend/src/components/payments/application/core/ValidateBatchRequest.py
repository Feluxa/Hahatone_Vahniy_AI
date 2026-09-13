from pydantic import BaseModel, Field

from components.payments.domain.BatchItem import BatchItem


class ValidateBatchRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=80)
    batch_reference: str = Field(min_length=1, max_length=100)
    items: tuple[BatchItem, ...] = Field(min_length=1, max_length=500)
