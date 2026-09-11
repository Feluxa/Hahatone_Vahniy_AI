from pydantic import BaseModel, Field, field_validator


class ReverseTransferRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=80)
    transfer_id: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=280)
    idempotency_key: str = Field(min_length=1, max_length=120)

    @field_validator("tenant_id", "transfer_id", "reason", "idempotency_key")
    @classmethod
    def strip_required(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value cannot be blank")
        return cleaned
