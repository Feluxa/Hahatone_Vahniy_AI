from components.payments.application.core.IGetTransferQuery import IGetTransferQuery
from components.payments.application.core.ISubmitTransferCommand import ISubmitTransferCommand
from components.payments.application.core.SubmitTransferRequest import SubmitTransferRequest
from components.payments.domain.TransferIntent import TransferIntent


class PaymentViews:
    """Framework-neutral callables that a future HTTP adapter may wrap."""

    def __init__(self, submit_transfer: ISubmitTransferCommand, get_transfer: IGetTransferQuery) -> None:
        self._submit_transfer = submit_transfer
        self._get_transfer = get_transfer

    async def submit(self, payload: dict[str, object]) -> TransferIntent:
        request = SubmitTransferRequest.model_validate(payload)
        return await self._submit_transfer.execute(request)

    async def get(self, tenant_id: str, transfer_id: str) -> TransferIntent:
        return await self._get_transfer.execute(tenant_id=tenant_id, transfer_id=transfer_id)
