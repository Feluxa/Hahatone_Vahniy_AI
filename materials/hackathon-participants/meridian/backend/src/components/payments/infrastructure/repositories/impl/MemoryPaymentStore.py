import asyncio

from components.payments.domain.TransferIntent import TransferIntent
from pydantic import BaseModel


class MemoryPaymentStore:
    """Single-process demo store; it provides no cross-process concurrency guarantees."""

    def __init__(self) -> None:
        self.intents: dict[tuple[str, str], TransferIntent] = {}
        self.idempotency: dict[tuple[str, str], str] = {}
        self.outbox: list[BaseModel] = []
        self.outbox_lock = asyncio.Lock()

    def snapshot(self) -> dict[tuple[str, str], TransferIntent]:
        return {key: value.model_copy(deep=True) for key, value in self.intents.items()}

    def transaction_snapshot(self) -> tuple[
        dict[tuple[str, str], TransferIntent], dict[tuple[str, str], str], list[BaseModel]
    ]:
        return (
            self.snapshot(),
            dict(self.idempotency),
            [event.model_copy(deep=True) for event in self.outbox],
        )

    def restore(self, snapshot: tuple[dict[tuple[str, str], TransferIntent], dict[tuple[str, str], str], list[BaseModel]]) -> None:
        intents, idempotency, outbox = snapshot
        self.intents = intents
        self.idempotency = idempotency
        self.outbox = outbox
