import asyncio

import pytest
from dishka import Provider, Scope, make_async_container, provide
from pydantic import BaseModel

from common.events.IEventBus import IEventBus
from common.events.MemoryEventBus import MemoryEventBus
from components.payments.application.core.IGetTransferQuery import IGetTransferQuery
from components.payments.application.core.ISubmitTransferCommand import ISubmitTransferCommand
from components.payments.application.core.SubmitTransferRequest import SubmitTransferRequest
from components.payments.domain.TransferAccepted import TransferAccepted
from components.payments.domain.TransferIntent import TransferIntent
from components.payments.infrastructure.PaymentsApplicationProvider import PaymentsApplicationProvider
from components.payments.infrastructure.PaymentsInfrastructureProvider import PaymentsInfrastructureProvider
from components.payments.infrastructure.repositories.core.ITransferIntentWritePort import (
    ITransferIntentWritePort,
)
from components.payments.infrastructure.repositories.impl.MemoryPaymentStore import MemoryPaymentStore
from components.payments.infrastructure.repositories.impl.MemoryTransferIntentRepository import (
    MemoryTransferIntentRepository,
)
from components.payments.infrastructure.uow.MemoryPaymentsUnitOfWork import MemoryPaymentsUnitOfWork


class EventBusProvider(Provider):
    scope = Scope.APP

    @provide(provides=IEventBus, scope=Scope.APP)
    def event_bus(self) -> IEventBus:
        return MemoryEventBus()


class FailingWritePort(ITransferIntentWritePort):
    def __init__(self, delegate: MemoryTransferIntentRepository) -> None:
        self._delegate = delegate
        self._inserts = 0

    def insert(self, intent: TransferIntent) -> None:
        self._inserts += 1
        if self._inserts == 2:
            raise RuntimeError("synthetic disk failure")
        self._delegate.insert(intent)

    def replace(self, intent: TransferIntent) -> None:
        self._delegate.replace(intent)

    def remove(self, intent: TransferIntent) -> None:
        self._delegate.remove(intent)


class FailOnceEventBus(IEventBus):
    def __init__(self) -> None:
        self.attempts = 0
        self.events: list[BaseModel] = []

    async def publish(self, event: BaseModel) -> None:
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError("synthetic broker failure")
        self.events.append(event.model_copy(deep=True))


class YieldingEventBus(IEventBus):
    def __init__(self) -> None:
        self.events: list[BaseModel] = []

    async def publish(self, event: BaseModel) -> None:
        await asyncio.sleep(0)
        self.events.append(event.model_copy(deep=True))


def test_dishka_provider_resolves_command_and_shared_store() -> None:
    async def scenario() -> None:
        container = make_async_container(
            PaymentsInfrastructureProvider(), PaymentsApplicationProvider(), EventBusProvider()
        )
        try:
            store = await container.get(MemoryPaymentStore)
            async with container() as request_scope:
                command = await request_scope.get(ISubmitTransferCommand)
                result = await command.execute(
                    SubmitTransferRequest.model_validate(
                        {
                            "tenant_id": "provider-tenant",
                            "source_account_id": "source",
                            "destination_account_id": "destination",
                            "amount": {"amount": "9.2500", "currency": "RUB"},
                            "idempotency_key": "provider-submit",
                        }
                    )
                )
                query = await request_scope.get(IGetTransferQuery)
                loaded = await query.execute(
                    tenant_id="provider-tenant", transfer_id=result.transfer_id
                )
            assert loaded.transfer_id == result.transfer_id
            assert len(store.intents) == 1
        finally:
            await container.close()

    asyncio.run(scenario())


def test_dishka_provider_reuses_app_scoped_store_between_request_scopes() -> None:
    async def scenario() -> None:
        container = make_async_container(
            PaymentsInfrastructureProvider(), PaymentsApplicationProvider(), EventBusProvider()
        )
        try:
            async with container() as first_scope:
                first_command = await first_scope.get(ISubmitTransferCommand)
                result = await first_command.execute(
                    SubmitTransferRequest.model_validate(
                        {
                            "tenant_id": "provider-tenant",
                            "source_account_id": "source",
                            "destination_account_id": "destination",
                            "amount": {"amount": "1.0000", "currency": "USD"},
                            "idempotency_key": "provider-scope",
                        }
                    )
                )
            async with container() as second_scope:
                query = await second_scope.get(IGetTransferQuery)
                loaded = await query.execute(
                    tenant_id="provider-tenant", transfer_id=result.transfer_id
                )
            assert loaded.amount.currency == "USD"
        finally:
            await container.close()

    asyncio.run(scenario())


def test_events_are_not_published_when_write_fails() -> None:
    async def scenario() -> None:
        store = MemoryPaymentStore()
        repository = MemoryTransferIntentRepository(store)
        events = MemoryEventBus()
        uow = MemoryPaymentsUnitOfWork(store, FailingWritePort(repository), events)
        first = TransferIntent(
            tenant_id="t",
            transfer_id="first",
            source_account_id="a",
            destination_account_id="b",
            amount={"amount": "1.0000", "currency": "RUB"},
            idempotency_key="key",
            request_fingerprint="f" * 64,
        )
        second = first.model_copy(update={"transfer_id": "second", "idempotency_key": "key-two"})
        uow.register_new(first)
        uow.register_new(second)
        uow.register_event(
            TransferAccepted(
                tenant_id="t",
                transfer_id="first",
                source_account_id="a",
                destination_account_id="b",
                amount=first.amount,
                occurred_at=first.created_at,
            )
        )
        with pytest.raises(RuntimeError, match="disk failure"):
            await uow.commit()
        assert events.events == []
        assert store.intents == {}

    asyncio.run(scenario())


def test_rollback_discards_pending_writes_and_events() -> None:
    async def scenario() -> None:
        store = MemoryPaymentStore()
        repository = MemoryTransferIntentRepository(store)
        events = MemoryEventBus()
        uow = MemoryPaymentsUnitOfWork(store, repository, events)
        intent = TransferIntent(
            tenant_id="t",
            transfer_id="x",
            source_account_id="a",
            destination_account_id="b",
            amount={"amount": "1.0000", "currency": "RUB"},
            idempotency_key="key",
            request_fingerprint="f" * 64,
        )
        uow.register_new(intent)
        uow.register_event(
            TransferAccepted(
                tenant_id="t", transfer_id="x", source_account_id="a", destination_account_id="b",
                amount=intent.amount, occurred_at=intent.created_at,
            )
        )
        await uow.rollback()
        assert store.intents == {}
        assert events.events == []
        with pytest.raises(RuntimeError, match="closed"):
            uow.register_new(intent)

    asyncio.run(scenario())


def test_unit_of_work_rejects_foreign_pydantic_model() -> None:
    class ForeignModel(BaseModel):
        value: str

    store = MemoryPaymentStore()
    uow = MemoryPaymentsUnitOfWork(store, MemoryTransferIntentRepository(store), MemoryEventBus())
    with pytest.raises(TypeError, match="TransferIntent"):
        uow.register_new(ForeignModel(value="not a payment"))


def test_memory_repository_has_explicit_demo_store_not_global_state() -> None:
    first_store = MemoryPaymentStore()
    second_store = MemoryPaymentStore()
    first = MemoryTransferIntentRepository(first_store)
    second = MemoryTransferIntentRepository(second_store)
    assert first._store is first_store
    assert second._store is second_store
    assert first._store is not second._store


def test_outbox_retains_committed_event_after_publish_failure_for_retry() -> None:
    async def scenario() -> None:
        store = MemoryPaymentStore()
        repository = MemoryTransferIntentRepository(store)
        event_bus = FailOnceEventBus()
        uow = MemoryPaymentsUnitOfWork(store, repository, event_bus)
        intent = TransferIntent(
            tenant_id="t",
            transfer_id="outbox-transfer",
            source_account_id="a",
            destination_account_id="b",
            amount={"amount": "1.0000", "currency": "RUB"},
            idempotency_key="outbox-key",
            request_fingerprint="f" * 64,
        )
        uow.register_new(intent)
        uow.register_event(
            TransferAccepted(
                tenant_id="t",
                transfer_id=intent.transfer_id,
                source_account_id="a",
                destination_account_id="b",
                amount=intent.amount,
                occurred_at=intent.created_at,
            )
        )
        with pytest.raises(RuntimeError, match="broker failure"):
            await uow.commit()
        assert ("t", "outbox-transfer") in store.intents
        assert len(store.outbox) == 1
        assert await uow.retry_dispatch() == 1
        assert store.outbox == []
        assert len(event_bus.events) == 1

    asyncio.run(scenario())


def test_concurrent_outbox_dispatchers_publish_each_event_once() -> None:
    async def scenario() -> None:
        store = MemoryPaymentStore()
        repository = MemoryTransferIntentRepository(store)
        event_bus = YieldingEventBus()
        first = TransferAccepted(
            tenant_id="t",
            transfer_id="first",
            source_account_id="a",
            destination_account_id="b",
            amount={"amount": "1.0000", "currency": "RUB"},
            occurred_at=TransferIntent(
                tenant_id="t",
                transfer_id="clock",
                source_account_id="a",
                destination_account_id="b",
                amount={"amount": "1.0000", "currency": "RUB"},
                idempotency_key="clock-key",
                request_fingerprint="f" * 64,
            ).created_at,
        )
        second = first.model_copy(update={"transfer_id": "second"})
        store.outbox.extend((first, second))
        one = MemoryPaymentsUnitOfWork(store, repository, event_bus)
        two = MemoryPaymentsUnitOfWork(store, repository, event_bus)
        dispatched = await asyncio.gather(one.retry_dispatch(), two.retry_dispatch())
        assert sum(dispatched) == 2
        assert [event.transfer_id for event in event_bus.events] == ["first", "second"]
        assert store.outbox == []

    asyncio.run(scenario())
