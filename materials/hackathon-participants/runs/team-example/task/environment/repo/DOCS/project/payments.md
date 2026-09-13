# Payments

`components.payments` records synthetic, tenant-bound transfer intents for Meridian Clearing. It is independent of lending and of the shared account/posting implementation. An accepted intent is a validated instruction; it does not itself mutate a ledger.

## Public application entrypoints

- `ISubmitTransferCommand.execute(SubmitTransferRequest)` accepts a transfer intent.
- `IReverseTransferCommand.execute(ReverseTransferRequest)` reverses a previously accepted intent.
- `IValidateBatchCommand.execute(ValidateBatchRequest)` performs pure preflight validation and does not persist intents.
- `IGetTransferQuery.execute(tenant_id=..., transfer_id=...)` returns one transfer or raises `TRANSFER_NOT_FOUND`.
- `IListTransfersQuery.execute(ListTransfersRequest)` returns newest-first records and an exclusive timestamp cursor.

Core interfaces use the `I` prefix. Their constructor-injected implementations are respectively `SubmitTransferCommand`, `ReverseTransferCommand`, `ValidateBatchCommand`, `GetTransferQuery`, and `ListTransfersQuery` in `application/impl`.

`PaymentViews` contains optional framework-neutral callable adapters. It validates an input mapping with Pydantic and delegates to the command or query. There is deliberately no FastAPI dependency.

## Money and validation

`Money` uses `Decimal` and requires at most four fractional digits. Binary floats are rejected before they can introduce a rounding ambiguity. Values normalize to four decimal places, so `"17"` becomes `Decimal("17.0000")`. Currency is a normalized three-letter ASCII code.

Submission requires a positive amount and distinct source and destination accounts. The component does not query balances or account status: those concerns belong to the account and posting boundary. Every repository read takes a tenant ID. A transfer ID known to another tenant is indistinguishable from a missing transfer.

Batch validation checks unique item references, account pairs, amounts, a per-item limit, and an aggregate source-account/currency limit. It returns all discovered issues for operator correction.

## Idempotency and reversal

Submission serializes the normalized, typed payload as sorted compact JSON with explicit JSON `null` values, then creates a SHA-256 fingerprint of its UTF-8 bytes. This preserves separators inside identifiers and distinguishes null from an empty optional value. Reusing the same tenant/key/payload returns the original intent without another write or event. Reusing a key with a different payload raises `IDEMPOTENCY_CONFLICT`. Keys are tenant-local.

A reversal is a state transition on the intent with an auditable reason, time, key, and version. Repeating the same reversal key returns the existing reversed intent; a different key raises `TRANSFER_ALREADY_REVERSED`. A later posting implementation can use this state to create separate, signed compensating postings rather than deleting the original instruction.

## Local demo assembly

Composition uses two Dishka providers with separate scopes. `PaymentsInfrastructureProvider` supplies application-scoped `MemoryPaymentStore`, `MemoryTransferIntentRepository`, and public read/write port aliases. `PaymentsApplicationProvider` supplies request-scoped `MemoryPaymentsUnitOfWork` and public command/query interface aliases.

The caller must also provide application-scoped `common.events.IEventBus.IEventBus`. The test provider uses `MemoryEventBus`. A typical host creates `make_async_container(PaymentsInfrastructureProvider(), PaymentsApplicationProvider(), event_bus_provider)`, enters `async with container() as request_scope`, then resolves `ISubmitTransferCommand` with `await request_scope.get(ISubmitTransferCommand)`.

`MemoryPaymentStore` and `MemoryTransferIntentRepository` are explicitly a single-process demo adapter. They copy values at their boundary but do not offer durable storage, distributed locking, or cross-process idempotency. Production persistence should implement the same read and write ports with a database transaction and a tenant/key uniqueness constraint.

## Commit and events

All mutations are registered with `MemoryPaymentsUnitOfWork`, which implements shared `IUnitOfWork`. Payments adds `IEventStagingUnitOfWork.register_event` for events that must be emitted after a successful commit. The memory UoW snapshots its store before a multi-write commit and restores that snapshot if any write fails. It appends events to the store's in-memory outbox in the same successful memory transaction, then dispatches them in order. If a publish fails, the committed intent remains and the undispatched event remains in the outbox; callers may invoke `retry_dispatch()` on that UoW instance. This is a local retry mechanism only, with no durability or cross-process delivery guarantee.

## Verification

From `meridian/`:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend/src \
  .venv/bin/python -m pytest tests/payments -q
```

The command runs the provider smoke test, including two request scopes sharing one application store. Tests use `asyncio.run`; no async pytest plugin is required.
