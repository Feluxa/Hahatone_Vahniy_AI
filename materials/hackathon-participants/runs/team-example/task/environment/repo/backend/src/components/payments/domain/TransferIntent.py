from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from components.payments.domain.Money import Money
from components.payments.domain.TransferState import TransferState


class TransferIntent(BaseModel):
    """A tenant-bound instruction accepted for a future ledger posting."""

    model_config = ConfigDict(validate_assignment=True)

    tenant_id: str = Field(min_length=1, max_length=80)
    transfer_id: str = Field(min_length=1, max_length=100)
    source_account_id: str = Field(min_length=1, max_length=100)
    destination_account_id: str = Field(min_length=1, max_length=100)
    amount: Money
    idempotency_key: str = Field(min_length=1, max_length=120)
    request_fingerprint: str = Field(min_length=64, max_length=64)
    state: TransferState = TransferState.ACCEPTED
    memo: str | None = Field(default=None, max_length=280)
    client_reference: str | None = Field(default=None, max_length=100)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reversed_at: datetime | None = None
    reversal_reason: str | None = Field(default=None, max_length=280)
    reversal_idempotency_key: str | None = Field(default=None, max_length=120)
    version: int = Field(default=1, ge=1)

    @field_validator("tenant_id", "transfer_id", "source_account_id", "destination_account_id")
    @classmethod
    def strip_identifiers(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("identifier cannot be blank")
        return cleaned

    @field_validator("idempotency_key", "reversal_idempotency_key")
    @classmethod
    def strip_key(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def validate_shape(self) -> "TransferIntent":
        if self.source_account_id == self.destination_account_id:
            raise ValueError("source and destination account must differ")
        if not self.amount.is_positive():
            raise ValueError("transfer amount must be positive")
        if self.state is TransferState.REVERSED:
            if self.reversed_at is None or not self.reversal_reason:
                raise ValueError("reversed transfer requires timestamp and reason")
        elif self.reversed_at is not None or self.reversal_reason is not None:
            raise ValueError("accepted transfer cannot have reversal details")
        return self

    def reversed(self, *, reason: str, idempotency_key: str, occurred_at: datetime) -> "TransferIntent":
        cleaned_reason = reason.strip()
        if not cleaned_reason:
            raise ValueError("reversal reason cannot be blank")
        return TransferIntent.model_validate(
            {
                **self.model_dump(),
                "state": TransferState.REVERSED,
                "reversed_at": occurred_at,
                "reversal_reason": cleaned_reason,
                "reversal_idempotency_key": idempotency_key,
                "version": self.version + 1,
            }
        )
