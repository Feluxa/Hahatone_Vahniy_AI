from abc import ABC, abstractmethod

from components.payments.application.core.ListTransfersRequest import ListTransfersRequest
from components.payments.application.core.TransferPage import TransferPage


class IListTransfersQuery(ABC):
    @abstractmethod
    async def execute(self, request: ListTransfersRequest) -> TransferPage:
        raise NotImplementedError
