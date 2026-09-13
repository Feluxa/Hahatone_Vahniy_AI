from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from components.payments.application.core.IEventStagingUnitOfWork import IEventStagingUnitOfWork
from components.payments.application.core.ISubmitTransferCommand import ISubmitTransferCommand
from components.payments.application.core.SubmitTransferRequest import SubmitTransferRequest
from components.payments.domain.IdempotencyConflictError import IdempotencyConflictError
from components.payments.domain.TransferAccepted import TransferAccepted
from components.payments.domain.TransferIntent import TransferIntent
from components.payments.infrastructure.repositories.core.ITransferIntentReadRepository import (
    ITransferIntentReadRepository,
)


class SubmitTransferCommand(ISubmitTransferCommand):
    def __init__(
        self,
        repository: ITransferIntentReadRepository,
        unit_of_work: IEventStagingUnitOfWork,
    ) -> None:
        self._repository = repository
        self._unit_of_work = unit_of_work

    async def execute(self, request: SubmitTransferRequest) -> TransferIntent:
        fingerprint = sha256(request.canonical_payload().encode("utf-8")).hexdigest()
        existing = await self._repository.find_by_idempotency_key(
            tenant_id=request.tenant_id,
            idempotency_key=request.idempotency_key,
        )
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise IdempotencyConflictError(details={"idempotency_key": request.idempotency_key})
            return existing

        occurred_at = datetime.now(timezone.utc)
        intent = TransferIntent(
            tenant_id=request.tenant_id,
            transfer_id=str(uuid4()),
            source_account_id=request.source_account_id,
            destination_account_id=request.destination_account_id,
            amount=request.amount,
            idempotency_key=request.idempotency_key,
            request_fingerprint=fingerprint,
            memo=request.memo,
            client_reference=request.client_reference,
            created_at=occurred_at,
        )
        self._unit_of_work.register_new(intent)
        self._unit_of_work.register_event(
            TransferAccepted(
                tenant_id=intent.tenant_id,
                transfer_id=intent.transfer_id,
                source_account_id=intent.source_account_id,
                destination_account_id=intent.destination_account_id,
                amount=intent.amount,
                occurred_at=occurred_at,
            )
        )
        await self._unit_of_work.commit()
        return intent.model_copy(deep=True)
