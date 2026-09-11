from abc import ABC, abstractmethod
from datetime import datetime

from components.payments.domain.TransferIntent import TransferIntent
from components.payments.domain.TransferState import TransferState


class ITransferIntentReadRepository(ABC):
    """Read model boundary; every lookup requires a tenant identifier."""

    @abstractmethod
    async def find_by_id(self, *, tenant_id: str, transfer_id: str) -> TransferIntent | None:
        raise NotImplementedError

    @abstractmethod
    async def find_by_idempotency_key(
        self, *, tenant_id: str, idempotency_key: str
    ) -> TransferIntent | None:
        raise NotImplementedError

    @abstractmethod
    async def list_for_tenant(
        self,
        *,
        tenant_id: str,
        limit: int,
        created_before: datetime | None,
        state: TransferState | None,
    ) -> tuple[TransferIntent, ...]:
        raise NotImplementedError
