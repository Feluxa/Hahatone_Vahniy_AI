from abc import ABC, abstractmethod

from components.payments.domain.TransferIntent import TransferIntent


class IGetTransferQuery(ABC):
    @abstractmethod
    async def execute(self, *, tenant_id: str, transfer_id: str) -> TransferIntent:
        raise NotImplementedError
