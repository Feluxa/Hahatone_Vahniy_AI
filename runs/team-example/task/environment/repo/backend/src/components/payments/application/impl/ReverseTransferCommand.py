from datetime import datetime, timezone

from components.payments.application.core.IEventStagingUnitOfWork import IEventStagingUnitOfWork
from components.payments.application.core.IReverseTransferCommand import IReverseTransferCommand
from components.payments.application.core.ReverseTransferRequest import ReverseTransferRequest
from components.payments.domain.IdempotencyConflictError import IdempotencyConflictError
from components.payments.domain.TransferAlreadyReversedError import TransferAlreadyReversedError
from components.payments.domain.TransferIntent import TransferIntent
from components.payments.domain.TransferReversed import TransferReversed
from components.payments.domain.TransferState import TransferState
from components.payments.domain.TransferNotFoundError import TransferNotFoundError
from components.payments.infrastructure.repositories.core.ITransferIntentReadRepository import (
    ITransferIntentReadRepository,
)


class ReverseTransferCommand(IReverseTransferCommand):
    def __init__(
        self,
        repository: ITransferIntentReadRepository,
        unit_of_work: IEventStagingUnitOfWork,
    ) -> None:
        self._repository = repository
        self._unit_of_work = unit_of_work

    async def execute(self, request: ReverseTransferRequest) -> TransferIntent:
        intent = await self._repository.find_by_id(
            tenant_id=request.tenant_id,
            transfer_id=request.transfer_id,
        )
        if intent is None:
            raise TransferNotFoundError(details={"transfer_id": request.transfer_id})
        if intent.state is TransferState.REVERSED:
            if intent.reversal_idempotency_key == request.idempotency_key:
                return intent
            raise TransferAlreadyReversedError(details={"transfer_id": request.transfer_id})
        if intent.reversal_idempotency_key is not None:
            raise IdempotencyConflictError(details={"transfer_id": request.transfer_id})

        occurred_at = datetime.now(timezone.utc)
        intent = intent.reversed(
            reason=request.reason,
            idempotency_key=request.idempotency_key,
            occurred_at=occurred_at,
        )
        self._unit_of_work.register_dirty(intent)
        self._unit_of_work.register_event(
            TransferReversed(
                tenant_id=intent.tenant_id,
                transfer_id=intent.transfer_id,
                reason=request.reason,
                occurred_at=occurred_at,
            )
        )
        await self._unit_of_work.commit()
        return intent.model_copy(deep=True)
