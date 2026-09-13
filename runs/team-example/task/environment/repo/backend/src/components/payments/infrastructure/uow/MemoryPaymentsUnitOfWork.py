from pydantic import BaseModel

from common.events.IEventBus import IEventBus
from components.payments.application.core.IEventStagingUnitOfWork import IEventStagingUnitOfWork
from components.payments.domain.TransferIntent import TransferIntent
from components.payments.infrastructure.repositories.core.ITransferIntentWritePort import (
    ITransferIntentWritePort,
)
from components.payments.infrastructure.repositories.impl.MemoryPaymentStore import MemoryPaymentStore


class MemoryPaymentsUnitOfWork(IEventStagingUnitOfWork):
    """A small transaction buffer for the single-process payments demonstration."""

    def __init__(
        self,
        store: MemoryPaymentStore,
        write_port: ITransferIntentWritePort,
        event_bus: IEventBus,
    ) -> None:
        self._store = store
        self._write_port = write_port
        self._event_bus = event_bus
        self._new: list[TransferIntent] = []
        self._dirty: list[TransferIntent] = []
        self._deleted: list[TransferIntent] = []
        self._events: list[BaseModel] = []
        self._closed = False

    def register_new(self, model: BaseModel) -> None:
        self._ensure_open()
        self._new.append(self._as_intent(model))

    def register_dirty(self, model: BaseModel) -> None:
        self._ensure_open()
        self._dirty.append(self._as_intent(model))

    def register_deleted(self, model: BaseModel) -> None:
        self._ensure_open()
        self._deleted.append(self._as_intent(model))

    def register_event(self, event: BaseModel) -> None:
        self._ensure_open()
        self._events.append(event.model_copy(deep=True))

    async def commit(self) -> None:
        self._ensure_open()
        snapshot = self._store.transaction_snapshot()
        try:
            for intent in self._new:
                self._write_port.insert(intent)
            for intent in self._dirty:
                self._write_port.replace(intent)
            for intent in self._deleted:
                self._write_port.remove(intent)
            self._store.outbox.extend(event.model_copy(deep=True) for event in self._events)
        except Exception:
            self._store.restore(snapshot)
            self._clear()
            self._closed = True
            raise
        self._closed = True
        self._clear()

        await self.retry_dispatch()

    async def retry_dispatch(self) -> int:
        dispatched = 0
        async with self._store.outbox_lock:
            while self._store.outbox:
                event = self._store.outbox[0]
                await self._event_bus.publish(event)
                self._store.outbox.pop(0)
                dispatched += 1
        return dispatched

    async def rollback(self) -> None:
        self._clear()
        self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("unit of work is already closed")

    def _as_intent(self, model: BaseModel) -> TransferIntent:
        if not isinstance(model, TransferIntent):
            raise TypeError("payments unit of work only persists TransferIntent")
        return model.model_copy(deep=True)

    def _clear(self) -> None:
        self._new.clear()
        self._dirty.clear()
        self._deleted.clear()
        self._events.clear()
