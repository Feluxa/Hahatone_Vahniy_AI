from abc import ABC, abstractmethod

from components.payments.application.core.ReverseTransferRequest import ReverseTransferRequest
from components.payments.domain.TransferIntent import TransferIntent


class IReverseTransferCommand(ABC):
    @abstractmethod
    async def execute(self, request: ReverseTransferRequest) -> TransferIntent:
        raise NotImplementedError
