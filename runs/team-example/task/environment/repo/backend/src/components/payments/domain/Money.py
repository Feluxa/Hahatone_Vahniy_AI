from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, field_validator


class Money(BaseModel):
    """An amount expressed at Meridian's four-decimal ledger scale."""

    model_config = ConfigDict(frozen=True)

    amount: Decimal
    currency: str

    @field_validator("amount", mode="before")
    @classmethod
    def parse_amount(cls, value: Decimal | str | int | float) -> Decimal:
        if isinstance(value, float):
            raise ValueError("money must be supplied as Decimal, integer, or string")
        try:
            amount = Decimal(value)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("amount must be a decimal value") from exc
        if not amount.is_finite():
            raise ValueError("amount must be finite")
        if amount.as_tuple().exponent < -4:
            raise ValueError("amount supports at most four fractional digits")
        return amount.quantize(Decimal("0.0001"))

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha() or not normalized.isascii():
            raise ValueError("currency must be a three-letter ASCII code")
        return normalized

    def is_positive(self) -> bool:
        return self.amount > Decimal("0.0000")

    def negate(self) -> "Money":
        return Money(amount=-self.amount, currency=self.currency)

    def same_currency(self, other: "Money") -> bool:
        return self.currency == other.currency
