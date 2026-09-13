from pydantic import BaseModel, Field

from components.payments.domain.Money import Money


class BatchItem(BaseModel):
    item_reference: str = Field(min_length=1, max_length=100)
    source_account_id: str = Field(min_length=1, max_length=100)
    destination_account_id: str = Field(min_length=1, max_length=100)
    amount: Money
    memo: str | None = Field(default=None, max_length=280)
