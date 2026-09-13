from components.payments.application.core.IListTransfersQuery import IListTransfersQuery
from components.payments.application.core.ListTransfersRequest import ListTransfersRequest
from components.payments.application.core.TransferPage import TransferPage
from components.payments.infrastructure.repositories.core.ITransferIntentReadRepository import (
    ITransferIntentReadRepository,
)


class ListTransfersQuery(IListTransfersQuery):
    def __init__(self, repository: ITransferIntentReadRepository) -> None:
        self._repository = repository

    async def execute(self, request: ListTransfersRequest) -> TransferPage:
        records = await self._repository.list_for_tenant(
            tenant_id=request.tenant_id,
            limit=request.limit + 1,
            created_before=request.cursor,
            state=request.state,
        )
        page = records[: request.limit]
        next_cursor = page[-1].created_at if len(records) > request.limit and page else None
        return TransferPage(items=page, next_cursor=next_cursor)
