from abc import ABC, abstractmethod

from components.payments.domain.TransferIntent import TransferIntent


class ITransferIntentWritePort(ABC):
    """Persistence port used only by the payments unit of work."""

    @abstractmethod
    def insert(self, intent: TransferIntent) -> None:
        raise NotImplementedError

    @abstractmethod
    def replace(self, intent: TransferIntent) -> None:
        raise NotImplementedError

    @abstractmethod
    def remove(self, intent: TransferIntent) -> None:
        raise NotImplementedError
