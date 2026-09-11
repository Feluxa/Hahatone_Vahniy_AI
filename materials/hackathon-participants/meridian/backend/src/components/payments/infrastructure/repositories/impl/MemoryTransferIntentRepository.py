from datetime import datetime

from components.payments.domain.TransferIntent import TransferIntent
from components.payments.domain.TransferState import TransferState
from components.payments.infrastructure.repositories.core.ITransferIntentReadRepository import (
    ITransferIntentReadRepository,
)
from components.payments.infrastructure.repositories.core.ITransferIntentWritePort import (
    ITransferIntentWritePort,
)
from components.payments.infrastructure.repositories.impl.MemoryPaymentStore import MemoryPaymentStore


class MemoryTransferIntentRepository(ITransferIntentReadRepository, ITransferIntentWritePort):
    """Copying repository for deterministic local demos and tests only."""

    def __init__(self, store: MemoryPaymentStore) -> None:
        self._store = store

    async def find_by_id(self, *, tenant_id: str, transfer_id: str) -> TransferIntent | None:
        intent = self._store.intents.get((tenant_id, transfer_id))
        return intent.model_copy(deep=True) if intent is not None else None

    async def find_by_idempotency_key(
        self, *, tenant_id: str, idempotency_key: str
    ) -> TransferIntent | None:
        transfer_id = self._store.idempotency.get((tenant_id, idempotency_key))
        if transfer_id is None:
            return None
        return await self.find_by_id(tenant_id=tenant_id, transfer_id=transfer_id)

    async def list_for_tenant(
        self,
        *,
        tenant_id: str,
        limit: int,
        created_before: datetime | None,
        state: TransferState | None,
    ) -> tuple[TransferIntent, ...]:
        matching = [
            intent.model_copy(deep=True)
            for (stored_tenant, _), intent in self._store.intents.items()
            if stored_tenant == tenant_id
            and (created_before is None or intent.created_at < created_before)
            and (state is None or intent.state is state)
        ]
        matching.sort(key=lambda item: (item.created_at, item.transfer_id), reverse=True)
        return tuple(matching[:limit])

    def insert(self, intent: TransferIntent) -> None:
        key = (intent.tenant_id, intent.transfer_id)
        idempotency_key = (intent.tenant_id, intent.idempotency_key)
        if key in self._store.intents or idempotency_key in self._store.idempotency:
            raise ValueError("duplicate transfer intent")
        self._store.intents[key] = intent.model_copy(deep=True)
        self._store.idempotency[idempotency_key] = intent.transfer_id

    def replace(self, intent: TransferIntent) -> None:
        key = (intent.tenant_id, intent.transfer_id)
        if key not in self._store.intents:
            raise ValueError("cannot replace missing transfer intent")
        self._store.intents[key] = intent.model_copy(deep=True)

    def remove(self, intent: TransferIntent) -> None:
        key = (intent.tenant_id, intent.transfer_id)
        self._store.intents.pop(key, None)
        self._store.idempotency.pop((intent.tenant_id, intent.idempotency_key), None)
