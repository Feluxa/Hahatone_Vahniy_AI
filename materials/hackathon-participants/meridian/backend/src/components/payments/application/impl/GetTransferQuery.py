from components.payments.application.core.IGetTransferQuery import IGetTransferQuery
from components.payments.domain.TransferIntent import TransferIntent
from components.payments.domain.TransferNotFoundError import TransferNotFoundError
from components.payments.infrastructure.repositories.core.ITransferIntentReadRepository import (
    ITransferIntentReadRepository,
)


class GetTransferQuery(IGetTransferQuery):
    def __init__(self, repository: ITransferIntentReadRepository) -> None:
        self._repository = repository

    async def execute(self, *, tenant_id: str, transfer_id: str) -> TransferIntent:
        intent = await self._repository.find_by_id(tenant_id=tenant_id, transfer_id=transfer_id)
        if intent is None:
            raise TransferNotFoundError(details={"transfer_id": transfer_id})
        return intent
