from abc import ABC, abstractmethod

from components.payments.application.core.SubmitTransferRequest import SubmitTransferRequest
from components.payments.domain.TransferIntent import TransferIntent


class ISubmitTransferCommand(ABC):
    @abstractmethod
    async def execute(self, request: SubmitTransferRequest) -> TransferIntent:
        raise NotImplementedError
