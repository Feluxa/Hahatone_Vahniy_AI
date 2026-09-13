import json

from pydantic import BaseModel, Field, field_validator

from components.payments.domain.Money import Money


class SubmitTransferRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=80)
    source_account_id: str = Field(min_length=1, max_length=100)
    destination_account_id: str = Field(min_length=1, max_length=100)
    amount: Money
    idempotency_key: str = Field(min_length=1, max_length=120)
    memo: str | None = Field(default=None, max_length=280)
    client_reference: str | None = Field(default=None, max_length=100)

    @field_validator("tenant_id", "source_account_id", "destination_account_id", "idempotency_key")
    @classmethod
    def strip_required(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value cannot be blank")
        return cleaned

    def canonical_payload(self) -> str:
        payload = {
            "amount": format(self.amount.amount, ".4f"),
            "client_reference": self.client_reference,
            "currency": self.amount.currency,
            "destination_account_id": self.destination_account_id,
            "memo": self.memo,
            "source_account_id": self.source_account_id,
            "tenant_id": self.tenant_id,
        }
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
