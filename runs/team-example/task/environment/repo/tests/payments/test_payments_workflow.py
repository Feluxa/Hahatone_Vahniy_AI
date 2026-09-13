import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from common.events.MemoryEventBus import MemoryEventBus
from components.payments.application.core.ListTransfersRequest import ListTransfersRequest
from components.payments.application.core.ReverseTransferRequest import ReverseTransferRequest
from components.payments.application.core.SubmitTransferRequest import SubmitTransferRequest
from components.payments.application.core.ValidateBatchRequest import ValidateBatchRequest
from components.payments.application.impl.GetTransferQuery import GetTransferQuery
from components.payments.application.impl.ListTransfersQuery import ListTransfersQuery
from components.payments.application.impl.ReverseTransferCommand import ReverseTransferCommand
from components.payments.application.impl.SubmitTransferCommand import SubmitTransferCommand
from components.payments.application.impl.ValidateBatchCommand import ValidateBatchCommand
from components.payments.domain.BatchItem import BatchItem
from components.payments.domain.IdempotencyConflictError import IdempotencyConflictError
from components.payments.domain.Money import Money
from components.payments.domain.TransferAlreadyReversedError import TransferAlreadyReversedError
from components.payments.domain.TransferNotFoundError import TransferNotFoundError
from components.payments.domain.TransferState import TransferState
from components.payments.infrastructure.repositories.impl.MemoryPaymentStore import MemoryPaymentStore
from components.payments.infrastructure.repositories.impl.MemoryTransferIntentRepository import (
    MemoryTransferIntentRepository,
)
from components.payments.infrastructure.uow.MemoryPaymentsUnitOfWork import MemoryPaymentsUnitOfWork
from components.payments.web.PaymentViews import PaymentViews


def build_services():
    store = MemoryPaymentStore()
    repository = MemoryTransferIntentRepository(store)
    events = MemoryEventBus()

    def submit():
        return SubmitTransferCommand(repository, MemoryPaymentsUnitOfWork(store, repository, events))

    def reverse():
        return ReverseTransferCommand(repository, MemoryPaymentsUnitOfWork(store, repository, events))

    return repository, events, submit, reverse


def request(**overrides: object) -> SubmitTransferRequest:
    payload: dict[str, object] = {
        "tenant_id": "tenant-north",
        "source_account_id": "acct-source",
        "destination_account_id": "acct-destination",
        "amount": {"amount": "125.5000", "currency": "rub"},
        "idempotency_key": "submit-001",
        "memo": "synthetic payroll clearing",
        "client_reference": "client-ref-1",
    }
    payload.update(overrides)
    return SubmitTransferRequest.model_validate(payload)


def reverse_request(transfer_id: str, **overrides: object) -> ReverseTransferRequest:
    payload: dict[str, object] = {
        "tenant_id": "tenant-north",
        "transfer_id": transfer_id,
        "reason": "duplicate synthetic instruction",
        "idempotency_key": "reverse-001",
    }
    payload.update(overrides)
    return ReverseTransferRequest.model_validate(payload)


def test_money_quantizes_integer_and_preserves_decimal_scale() -> None:
    money = Money(amount="17", currency=" rub ")
    assert money.amount == Decimal("17.0000")
    assert money.currency == "RUB"
    assert money.model_dump(mode="json") == {"amount": "17.0000", "currency": "RUB"}


def test_money_rejects_float_precision_ambiguity() -> None:
    with pytest.raises(ValidationError, match="Decimal"):
        Money(amount=1.25, currency="RUB")


def test_money_rejects_more_than_four_fractional_digits() -> None:
    with pytest.raises(ValidationError, match="four fractional"):
        Money(amount="1.00001", currency="RUB")


def test_money_rejects_non_finite_values() -> None:
    with pytest.raises(ValidationError, match="finite"):
        Money(amount="NaN", currency="RUB")


def test_money_rejects_invalid_currency() -> None:
    with pytest.raises(ValidationError, match="three-letter"):
        Money(amount="1.0000", currency="РУБ")


def test_submit_persists_an_accepted_intent_and_publishes_after_commit() -> None:
    repository, events, submit, _ = build_services()
    intent = asyncio.run(submit().execute(request()))
    stored = asyncio.run(repository.find_by_id(tenant_id="tenant-north", transfer_id=intent.transfer_id))
    assert stored is not None
    assert stored.state is TransferState.ACCEPTED
    assert stored.amount.amount == Decimal("125.5000")
    assert len(events.events) == 1
    assert events.events[0].transfer_id == intent.transfer_id


def test_submit_is_idempotent_for_identical_request() -> None:
    _, events, submit, _ = build_services()
    first = asyncio.run(submit().execute(request()))
    second = asyncio.run(submit().execute(request()))
    assert second.transfer_id == first.transfer_id
    assert second.created_at == first.created_at
    assert len(events.events) == 1


def test_submit_rejects_idempotency_key_reused_with_other_amount() -> None:
    _, _, submit, _ = build_services()
    asyncio.run(submit().execute(request()))
    with pytest.raises(IdempotencyConflictError) as error:
        asyncio.run(submit().execute(request(amount={"amount": "126.0000", "currency": "RUB"})))
    assert error.value.code == "IDEMPOTENCY_CONFLICT"


def test_submit_rejects_idempotency_key_reused_with_other_account() -> None:
    _, _, submit, _ = build_services()
    asyncio.run(submit().execute(request()))
    with pytest.raises(IdempotencyConflictError):
        asyncio.run(submit().execute(request(destination_account_id="other-account")))


def test_submit_allows_same_idempotency_key_in_another_tenant() -> None:
    _, events, submit, _ = build_services()
    north = asyncio.run(submit().execute(request()))
    south = asyncio.run(
        submit().execute(request(tenant_id="tenant-south", source_account_id="source-south"))
    )
    assert north.transfer_id != south.transfer_id
    assert len(events.events) == 2


def test_submit_validates_accounts_differ_at_domain_boundary() -> None:
    with pytest.raises(ValidationError, match="must differ"):
        asyncio.run(
            build_services()[2]().execute(
                request(source_account_id="same", destination_account_id="same")
            )
        )


def test_submit_validates_positive_amount_at_domain_boundary() -> None:
    with pytest.raises(ValidationError, match="positive"):
        asyncio.run(build_services()[2]().execute(request(amount={"amount": "0", "currency": "RUB"})))


def test_repository_returns_a_copy_not_mutable_store_state() -> None:
    repository, _, submit, _ = build_services()
    intent = asyncio.run(submit().execute(request()))
    fetched = asyncio.run(repository.find_by_id(tenant_id="tenant-north", transfer_id=intent.transfer_id))
    assert fetched is not None
    fetched.memo = "caller mutation"
    again = asyncio.run(repository.find_by_id(tenant_id="tenant-north", transfer_id=intent.transfer_id))
    assert again is not None
    assert again.memo == "synthetic payroll clearing"


def test_get_query_enforces_tenant_isolation() -> None:
    repository, _, submit, _ = build_services()
    intent = asyncio.run(submit().execute(request()))
    query = GetTransferQuery(repository)
    with pytest.raises(TransferNotFoundError):
        asyncio.run(query.execute(tenant_id="tenant-south", transfer_id=intent.transfer_id))


def test_repository_idempotency_lookup_enforces_tenant_isolation() -> None:
    repository, _, submit, _ = build_services()
    asyncio.run(submit().execute(request()))
    found = asyncio.run(
        repository.find_by_idempotency_key(tenant_id="tenant-south", idempotency_key="submit-001")
    )
    assert found is None


def test_reversal_persists_state_and_emits_only_after_commit() -> None:
    repository, events, submit, reverse = build_services()
    original = asyncio.run(submit().execute(request()))
    reversed_intent = asyncio.run(reverse().execute(reverse_request(original.transfer_id)))
    stored = asyncio.run(repository.find_by_id(tenant_id="tenant-north", transfer_id=original.transfer_id))
    assert reversed_intent.state is TransferState.REVERSED
    assert reversed_intent.reversal_reason == "duplicate synthetic instruction"
    assert stored is not None and stored.state is TransferState.REVERSED
    assert len(events.events) == 2
    assert events.events[-1].transfer_id == original.transfer_id


def test_reversal_is_idempotent_for_same_reversal_key() -> None:
    _, events, submit, reverse = build_services()
    original = asyncio.run(submit().execute(request()))
    first = asyncio.run(reverse().execute(reverse_request(original.transfer_id)))
    second = asyncio.run(reverse().execute(reverse_request(original.transfer_id)))
    assert first.version == 2
    assert second.version == 2
    assert len(events.events) == 2


def test_reversal_rejects_different_reversal_key() -> None:
    _, _, submit, reverse = build_services()
    original = asyncio.run(submit().execute(request()))
    asyncio.run(reverse().execute(reverse_request(original.transfer_id)))
    with pytest.raises(TransferAlreadyReversedError):
        asyncio.run(reverse().execute(reverse_request(original.transfer_id, idempotency_key="reverse-002")))


def test_reversal_does_not_cross_tenant_boundary() -> None:
    _, _, submit, reverse = build_services()
    original = asyncio.run(submit().execute(request()))
    with pytest.raises(TransferNotFoundError):
        asyncio.run(reverse().execute(reverse_request(original.transfer_id, tenant_id="tenant-south")))


def test_reversal_of_unknown_transfer_fails_with_stable_error() -> None:
    _, _, _, reverse = build_services()
    with pytest.raises(TransferNotFoundError) as error:
        asyncio.run(reverse().execute(reverse_request("missing-transfer")))
    assert error.value.code == "TRANSFER_NOT_FOUND"


def test_list_query_returns_only_requested_tenant() -> None:
    repository, _, submit, _ = build_services()
    asyncio.run(submit().execute(request(idempotency_key="north-1")))
    asyncio.run(submit().execute(request(tenant_id="tenant-south", idempotency_key="south-1")))
    page = asyncio.run(ListTransfersQuery(repository).execute(ListTransfersRequest(tenant_id="tenant-north")))
    assert len(page.items) == 1
    assert page.items[0].tenant_id == "tenant-north"


def test_list_query_filters_state() -> None:
    repository, _, submit, reverse = build_services()
    accepted = asyncio.run(submit().execute(request(idempotency_key="accepted")))
    reversed_intent = asyncio.run(submit().execute(request(idempotency_key="reversed")))
    asyncio.run(reverse().execute(reverse_request(reversed_intent.transfer_id)))
    page = asyncio.run(
        ListTransfersQuery(repository).execute(
            ListTransfersRequest(tenant_id="tenant-north", state=TransferState.ACCEPTED)
        )
    )
    assert [item.transfer_id for item in page.items] == [accepted.transfer_id]


def test_list_query_paginates_with_cursor() -> None:
    repository, _, submit, _ = build_services()
    first = asyncio.run(submit().execute(request(idempotency_key="one")))
    second = asyncio.run(submit().execute(request(idempotency_key="two")))
    page = asyncio.run(
        ListTransfersQuery(repository).execute(ListTransfersRequest(tenant_id="tenant-north", limit=1))
    )
    assert len(page.items) == 1
    assert page.next_cursor is not None
    next_page = asyncio.run(
        ListTransfersQuery(repository).execute(
            ListTransfersRequest(tenant_id="tenant-north", limit=2, cursor=page.next_cursor)
        )
    )
    assert {item.transfer_id for item in page.items + next_page.items} == {
        first.transfer_id,
        second.transfer_id,
    }


def test_batch_validation_accepts_well_formed_batch_without_persisting() -> None:
    service = ValidateBatchCommand()
    result = asyncio.run(
        service.execute(
            ValidateBatchRequest(
                tenant_id="tenant-north",
                batch_reference="batch-001",
                items=(
                    BatchItem(
                        item_reference="line-1",
                        source_account_id="a-1",
                        destination_account_id="b-1",
                        amount=Money(amount="1.0000", currency="RUB"),
                    ),
                ),
            )
        )
    )
    assert result.is_valid
    assert result.accepted_count == 1
    assert result.issues == ()


def test_batch_validation_reports_duplicate_reference_and_same_account() -> None:
    service = ValidateBatchCommand()
    items = (
        BatchItem(item_reference="line-1", source_account_id="a", destination_account_id="a", amount=Money(amount="1", currency="RUB")),
        BatchItem(item_reference="line-1", source_account_id="a", destination_account_id="b", amount=Money(amount="1", currency="RUB")),
    )
    result = asyncio.run(service.execute(ValidateBatchRequest(tenant_id="t", batch_reference="b", items=items)))
    assert not result.is_valid
    assert {issue.code for issue in result.issues} == {"DUPLICATE_ITEM_REFERENCE", "SAME_ACCOUNT"}
    assert result.rejected_count == 1


def test_batch_validation_reports_aggregate_source_limit() -> None:
    service = ValidateBatchCommand(maximum_amount=Decimal("10.0000"))
    items = (
        BatchItem(item_reference="1", source_account_id="a", destination_account_id="b", amount=Money(amount="6", currency="RUB")),
        BatchItem(item_reference="2", source_account_id="a", destination_account_id="c", amount=Money(amount="6", currency="RUB")),
    )
    result = asyncio.run(service.execute(ValidateBatchRequest(tenant_id="t", batch_reference="b", items=items)))
    assert any(issue.code == "SOURCE_AGGREGATE_LIMIT" for issue in result.issues)


def test_batch_validation_reports_per_item_limit() -> None:
    service = ValidateBatchCommand(maximum_amount=Decimal("10.0000"))
    item = BatchItem(item_reference="1", source_account_id="a", destination_account_id="b", amount=Money(amount="11", currency="RUB"))
    result = asyncio.run(service.execute(ValidateBatchRequest(tenant_id="t", batch_reference="b", items=(item,))))
    assert result.rejected_count == 1
    assert result.issues[0].code == "AMOUNT_LIMIT"


def test_batch_validation_reports_too_many_items() -> None:
    service = ValidateBatchCommand(maximum_items=1)
    items = (
        BatchItem(item_reference="1", source_account_id="a", destination_account_id="b", amount=Money(amount="1", currency="RUB")),
        BatchItem(item_reference="2", source_account_id="c", destination_account_id="d", amount=Money(amount="1", currency="RUB")),
    )
    result = asyncio.run(service.execute(ValidateBatchRequest(tenant_id="t", batch_reference="b", items=items)))
    assert result.rejected_count == 2
    assert result.issues[0].item_reference == "*"


def test_store_snapshot_is_deeply_isolated() -> None:
    repository, _, submit, _ = build_services()
    intent = asyncio.run(submit().execute(request()))
    snapshot = repository._store.snapshot()
    snapshot[("tenant-north", intent.transfer_id)].memo = "tampered snapshot"
    stored = asyncio.run(repository.find_by_id(tenant_id="tenant-north", transfer_id=intent.transfer_id))
    assert stored is not None and stored.memo == "synthetic payroll clearing"


def test_reverse_timestamp_is_timezone_aware() -> None:
    _, _, submit, reverse = build_services()
    original = asyncio.run(submit().execute(request()))
    reversed_intent = asyncio.run(reverse().execute(reverse_request(original.transfer_id)))
    assert reversed_intent.reversed_at is not None
    assert reversed_intent.reversed_at.tzinfo is timezone.utc


def test_transfer_domain_rejects_incomplete_reversed_shape() -> None:
    with pytest.raises(ValidationError, match="requires timestamp"):
        request_data = request().model_dump()
        request_data["transfer_id"] = "not-used"
        # This assertion exercises the model invariant indirectly through service-owned construction.
        from components.payments.domain.TransferIntent import TransferIntent
        TransferIntent(
            tenant_id="t", transfer_id="x", source_account_id="a", destination_account_id="b",
            amount=Money(amount="1", currency="RUB"), idempotency_key="i", request_fingerprint="a" * 64,
            state=TransferState.REVERSED,
        )


def test_list_cursor_is_strictly_before_previous_record() -> None:
    repository, _, submit, _ = build_services()
    item = asyncio.run(submit().execute(request()))
    records = asyncio.run(
        repository.list_for_tenant(
            tenant_id="tenant-north", limit=10, created_before=item.created_at, state=None
        )
    )
    assert records == ()


def test_reverse_reason_cannot_be_blank_after_normalization() -> None:
    with pytest.raises(ValidationError, match="blank"):
        ReverseTransferRequest(tenant_id="t", transfer_id="x", reason="   ", idempotency_key="r")


def test_list_request_limit_has_safe_upper_bound() -> None:
    with pytest.raises(ValidationError):
        ListTransfersRequest(tenant_id="t", limit=201)


def test_submit_request_canonical_payload_changes_when_memo_changes() -> None:
    original = request(memo="first memo")
    changed = request(memo="second memo")
    assert original.canonical_payload() != changed.canonical_payload()


def test_submit_request_canonical_payload_has_four_decimal_amount() -> None:
    normalized = request(amount={"amount": "2", "currency": "RUB"})
    assert "2.0000" in normalized.canonical_payload()


def test_canonical_payload_distinguishes_delimiter_positions() -> None:
    left = request(source_account_id="a|b", destination_account_id="c")
    right = request(source_account_id="a", destination_account_id="b|c")
    assert left.canonical_payload() != right.canonical_payload()


def test_canonical_payload_distinguishes_null_and_empty_optional_values() -> None:
    nulls = request(memo=None, client_reference=None)
    empty = request(memo="", client_reference="")
    assert nulls.canonical_payload() != empty.canonical_payload()


def test_submit_rejects_delimiter_collision_attempt_as_different_payload() -> None:
    _, _, submit, _ = build_services()
    asyncio.run(submit().execute(request(source_account_id="a|b", destination_account_id="c")))
    with pytest.raises(IdempotencyConflictError):
        asyncio.run(submit().execute(request(source_account_id="a", destination_account_id="b|c")))


def test_submit_request_normalizes_required_identifiers() -> None:
    normalized = request(
        tenant_id=" tenant-north ",
        source_account_id=" source ",
        destination_account_id=" destination ",
        idempotency_key=" key ",
    )
    assert normalized.tenant_id == "tenant-north"
    assert normalized.source_account_id == "source"
    assert normalized.destination_account_id == "destination"
    assert normalized.idempotency_key == "key"


def test_submit_request_rejects_blank_tenant_after_normalization() -> None:
    with pytest.raises(ValidationError, match="blank"):
        request(tenant_id="  ")


def test_submit_request_rejects_blank_idempotency_key_after_normalization() -> None:
    with pytest.raises(ValidationError, match="blank"):
        request(idempotency_key="  ")


def test_transfer_intent_accepts_optional_client_reference() -> None:
    _, _, submit, _ = build_services()
    intent = asyncio.run(submit().execute(request(client_reference="reference-009")))
    assert intent.client_reference == "reference-009"


def test_transfer_intent_can_omit_optional_memo_and_reference() -> None:
    _, _, submit, _ = build_services()
    intent = asyncio.run(submit().execute(request(memo=None, client_reference=None)))
    assert intent.memo is None
    assert intent.client_reference is None


def test_transfer_intent_rejects_accepted_shape_with_reversal_details() -> None:
    from components.payments.domain.TransferIntent import TransferIntent

    with pytest.raises(ValidationError, match="cannot have reversal details"):
        TransferIntent(
            tenant_id="t",
            transfer_id="x",
            source_account_id="a",
            destination_account_id="b",
            amount=Money(amount="1", currency="RUB"),
            idempotency_key="i",
            request_fingerprint="a" * 64,
            reversed_at=datetime.now(timezone.utc),
        )


def test_transfer_intent_reverse_returns_new_validated_instance() -> None:
    from components.payments.domain.TransferIntent import TransferIntent

    original = TransferIntent(
        tenant_id="t",
        transfer_id="x",
        source_account_id="a",
        destination_account_id="b",
        amount=Money(amount="1", currency="RUB"),
        idempotency_key="i",
        request_fingerprint="a" * 64,
    )
    replacement = original.reversed(
        reason="operator correction",
        idempotency_key="reverse-i",
        occurred_at=datetime.now(timezone.utc),
    )
    assert replacement is not original
    assert original.state is TransferState.ACCEPTED
    assert replacement.state is TransferState.REVERSED
    assert replacement.version == original.version + 1


def test_transfer_intent_reverse_rejects_blank_reason() -> None:
    from components.payments.domain.TransferIntent import TransferIntent

    original = TransferIntent(
        tenant_id="t",
        transfer_id="x",
        source_account_id="a",
        destination_account_id="b",
        amount=Money(amount="1", currency="RUB"),
        idempotency_key="i",
        request_fingerprint="a" * 64,
    )
    with pytest.raises(ValueError, match="blank"):
        original.reversed(
            reason="   ", idempotency_key="reverse-i", occurred_at=datetime.now(timezone.utc)
        )


def test_payment_views_submit_validates_mapping_at_boundary() -> None:
    repository, _, submit, _ = build_services()
    view = PaymentViews(submit(), GetTransferQuery(repository))
    intent = asyncio.run(
        view.submit(
            {
                "tenant_id": "view-tenant",
                "source_account_id": "source",
                "destination_account_id": "destination",
                "amount": {"amount": "3.0000", "currency": "EUR"},
                "idempotency_key": "view-submit",
            }
        )
    )
    assert intent.tenant_id == "view-tenant"
    assert intent.amount.currency == "EUR"


def test_payment_views_get_uses_explicit_tenant_parameter() -> None:
    repository, _, submit, _ = build_services()
    created = asyncio.run(submit().execute(request()))
    view = PaymentViews(submit(), GetTransferQuery(repository))
    loaded = asyncio.run(view.get("tenant-north", created.transfer_id))
    assert loaded.transfer_id == created.transfer_id


def test_payment_views_reject_invalid_mapping_without_writing() -> None:
    repository, _, submit, _ = build_services()
    view = PaymentViews(submit(), GetTransferQuery(repository))
    with pytest.raises(ValidationError):
        asyncio.run(view.submit({"tenant_id": "only-one-field"}))
    page = asyncio.run(ListTransfersQuery(repository).execute(ListTransfersRequest(tenant_id="tenant-north")))
    assert page.items == ()


def test_list_query_returns_none_cursor_when_results_fit_page() -> None:
    repository, _, submit, _ = build_services()
    asyncio.run(submit().execute(request()))
    page = asyncio.run(
        ListTransfersQuery(repository).execute(ListTransfersRequest(tenant_id="tenant-north", limit=10))
    )
    assert page.next_cursor is None


def test_list_query_returns_newest_first() -> None:
    repository, _, submit, _ = build_services()
    first = asyncio.run(submit().execute(request(idempotency_key="old")))
    second = asyncio.run(submit().execute(request(idempotency_key="new")))
    page = asyncio.run(
        ListTransfersQuery(repository).execute(ListTransfersRequest(tenant_id="tenant-north"))
    )
    assert page.items[0].transfer_id == second.transfer_id
    assert page.items[1].transfer_id == first.transfer_id


def test_repository_list_state_filter_returns_reversed_item() -> None:
    repository, _, submit, reverse = build_services()
    original = asyncio.run(submit().execute(request()))
    asyncio.run(reverse().execute(reverse_request(original.transfer_id)))
    records = asyncio.run(
        repository.list_for_tenant(
            tenant_id="tenant-north",
            limit=10,
            created_before=None,
            state=TransferState.REVERSED,
        )
    )
    assert [item.transfer_id for item in records] == [original.transfer_id]


def test_batch_validation_keeps_currencies_separate_for_aggregate_totals() -> None:
    service = ValidateBatchCommand(maximum_amount=Decimal("10.0000"))
    items = (
        BatchItem(item_reference="rub", source_account_id="a", destination_account_id="b", amount=Money(amount="8", currency="RUB")),
        BatchItem(item_reference="usd", source_account_id="a", destination_account_id="c", amount=Money(amount="8", currency="USD")),
    )
    result = asyncio.run(service.execute(ValidateBatchRequest(tenant_id="t", batch_reference="b", items=items)))
    assert result.is_valid
    assert result.accepted_count == 2
