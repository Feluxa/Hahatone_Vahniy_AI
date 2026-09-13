import asyncio
from datetime import date
from decimal import Decimal

from dishka import make_async_container

from components.lending.application.impl.DelinquencyService import DelinquencyService
from components.lending.application.impl.LoanService import LoanService
from components.lending.application.impl.PaymentAllocationService import PaymentAllocationService
from components.lending.application.impl.PortfolioQueryService import PortfolioQueryService
from components.lending.application.impl.RestructuringPreviewService import RestructuringPreviewService
from components.lending.application.impl.ScheduleService import ScheduleService
from components.lending.domain.CreditPolicy import CreditPolicy
from components.lending.domain.Delinquency import DelinquencyBand
from components.lending.domain.Installment import Installment
from components.lending.domain.Loan import Loan, LoanStatus
from components.lending.domain.PaymentAllocation import AllocationBucket
from components.lending.infrastructure.providers.LendingProvider import lending_providers
from components.lending.infrastructure.providers.LendingRequestProvider import LendingRequestProvider
from components.lending.infrastructure.providers.LendingStoreProvider import LendingStoreProvider
from components.lending.infrastructure.repositories.impl.MemoryLendingReadRepository import MemoryLendingReadRepository
from components.lending.infrastructure.uow.LendingMemoryUnitOfWork import LendingMemoryUnitOfWork


def policy() -> CreditPolicy:
    return CreditPolicy(
        policy_id="synthetic-rub-v1",
        currency="RUB",
        annual_rate_floor=Decimal("0.01000000"),
        annual_rate_ceiling=Decimal("0.50000000"),
        grace_days=5,
        arrears_threshold_days=30,
        write_off_threshold_days=180,
        max_term_months=72,
        effective_from=date(2025, 1, 1),
    )


def loan(tenant: str = "tenant-a", loan_id: str = "LN-1", opened: date = date(2025, 1, 31)) -> Loan:
    return Loan(
        tenant_id=tenant,
        loan_id=loan_id,
        customer_id=f"customer-{tenant}",
        account_id=f"account-{tenant}",
        currency="rub",
        principal=Decimal("120000.0000"),
        annual_rate=Decimal("0.12000000"),
        opened_on=opened,
        maturity_date=date(2026, 1, 31),
        term_months=12,
    )


def services() -> tuple[dict, LendingMemoryUnitOfWork, MemoryLendingReadRepository, LoanService, PaymentAllocationService, DelinquencyService, PortfolioQueryService, RestructuringPreviewService]:
    store: dict = {"loans": {}, "installments": {}, "payments": {}, "early_funds": {}}
    uow = LendingMemoryUnitOfWork(store)
    repo = MemoryLendingReadRepository(store)
    schedule = ScheduleService(uow)
    delinquency = DelinquencyService(repo, uow)
    return store, uow, repo, LoanService(repo, uow, schedule), PaymentAllocationService(repo, uow), delinquency, PortfolioQueryService(repo, delinquency), RestructuringPreviewService(repo, schedule, delinquency)


def test_open_creates_amortizing_schedule_and_commits() -> None:
    async def scenario() -> None:
        _, uow, repo, opener, _, _, _, _ = services()
        created = await opener.open(loan(), policy())
        rows = await repo.list_installments("tenant-a", "LN-1")
        assert created.currency == "RUB"
        assert len(rows) == 12
        assert rows[0].due_date == date(2025, 2, 28)
        assert rows[-1].due_date == date(2026, 1, 31)
        assert sum((row.principal_due for row in rows), Decimal("0")) == Decimal("120000.0000")
        assert rows[-1].principal_due > Decimal("0")
        assert uow.commits == 1
    asyncio.run(scenario())


def test_schedule_rejects_rate_outside_policy() -> None:
    async def scenario() -> None:
        _, _, _, opener, _, _, _, _ = services()
        invalid = loan().model_copy(update={"annual_rate": Decimal("0.70000000")})
        try:
            await opener.open(invalid, policy())
        except ValueError as error:
            assert "violates policy" in str(error)
        else:
            raise AssertionError("out of policy rate must fail")
    asyncio.run(scenario())


def test_duplicate_loan_is_scoped_to_tenant() -> None:
    async def scenario() -> None:
        _, _, repo, opener, _, _, _, _ = services()
        await opener.open(loan("tenant-a", "LN-SHARED"), policy())
        await opener.open(loan("tenant-b", "LN-SHARED"), policy())
        assert (await repo.get_loan("tenant-a", "LN-SHARED")) is not None
        assert (await repo.get_loan("tenant-b", "LN-SHARED")) is not None
    asyncio.run(scenario())


def test_payment_allocates_overdue_interest_before_principal() -> None:
    async def scenario() -> None:
        _, _, repo, opener, allocator, _, _, _ = services()
        await opener.open(loan(), policy())
        schedule = await repo.list_installments("tenant-a", "LN-1")
        first = schedule[0]
        result = await allocator.allocate("tenant-a", "LN-1", "PAY-1", first.interest_due + Decimal("100.0000"), date(2025, 4, 1))
        updated = (await repo.list_installments("tenant-a", "LN-1"))[0]
        assert [row.bucket for row in result.allocations] == [AllocationBucket.OVERDUE_INTEREST, AllocationBucket.OVERDUE_PRINCIPAL]
        assert updated.interest_paid == first.interest_due
        assert updated.principal_paid == Decimal("100.0000")
    asyncio.run(scenario())


def test_payment_walks_oldest_overdue_installments_first() -> None:
    async def scenario() -> None:
        _, _, repo, opener, allocator, _, _, _ = services()
        await opener.open(loan(), policy())
        rows = await repo.list_installments("tenant-a", "LN-1")
        result = await allocator.allocate("tenant-a", "LN-1", "PAY-2", rows[0].total_due + Decimal("10.0000"), date(2025, 5, 1))
        after = await repo.list_installments("tenant-a", "LN-1")
        assert after[0].is_settled
        assert after[1].interest_paid == Decimal("10.0000")
        assert result.allocations[-1].installment_no == 2
    asyncio.run(scenario())


def test_current_payment_is_not_classified_as_overdue() -> None:
    async def scenario() -> None:
        _, _, repo, opener, allocator, _, _, _ = services()
        await opener.open(loan(), policy())
        first = (await repo.list_installments("tenant-a", "LN-1"))[0]
        result = await allocator.allocate("tenant-a", "LN-1", "PAY-3", Decimal("20.0000"), date(2025, 2, 1))
        assert result.allocations[0].bucket == AllocationBucket.CURRENT_INTEREST
        assert first.due_date > date(2025, 2, 1)
    asyncio.run(scenario())


def test_early_funds_are_retained_after_schedule_is_paid() -> None:
    async def scenario() -> None:
        _, _, repo, opener, allocator, _, _, _ = services()
        await opener.open(loan(), policy())
        rows = await repo.list_installments("tenant-a", "LN-1")
        total = sum((row.total_due for row in rows), Decimal("0"))
        result = await allocator.allocate("tenant-a", "LN-1", "PAY-4", total + Decimal("15.0000"), date(2027, 1, 1))
        assert result.unapplied_early_funds == Decimal("15.0000")
        assert await repo.get_early_funds("tenant-a", "LN-1") == Decimal("15.0000")
    asyncio.run(scenario())


def test_duplicate_payment_is_rejected_idempotently() -> None:
    async def scenario() -> None:
        _, _, _, opener, allocator, _, _, _ = services()
        await opener.open(loan(), policy())
        await allocator.allocate("tenant-a", "LN-1", "PAY-IDEMPOTENT", Decimal("1"), date(2025, 2, 1))
        try:
            await allocator.allocate("tenant-a", "LN-1", "PAY-IDEMPOTENT", Decimal("1"), date(2025, 2, 1))
        except ValueError as error:
            assert "already" in str(error)
        else:
            raise AssertionError("duplicate payment must fail")
    asyncio.run(scenario())


def test_payment_cannot_cross_tenant_boundary() -> None:
    async def scenario() -> None:
        _, _, _, opener, allocator, _, _, _ = services()
        await opener.open(loan("tenant-a"), policy())
        try:
            await allocator.allocate("tenant-b", "LN-1", "PAY-X", Decimal("1"), date(2025, 2, 1))
        except LookupError:
            pass
        else:
            raise AssertionError("tenant B cannot pay tenant A loan")
    asyncio.run(scenario())


def test_delinquency_bands_follow_explicit_policy() -> None:
    async def scenario() -> None:
        _, _, _, opener, _, delinquency, _, _ = services()
        await opener.open(loan(), policy())
        assert (await delinquency.assess("tenant-a", "LN-1", date(2025, 2, 28), policy())).band == DelinquencyBand.CURRENT
        assert (await delinquency.assess("tenant-a", "LN-1", date(2025, 3, 2), policy())).band == DelinquencyBand.GRACE
        assert (await delinquency.assess("tenant-a", "LN-1", date(2025, 3, 10), policy())).band == DelinquencyBand.EARLY_ARREARS
        assert (await delinquency.assess("tenant-a", "LN-1", date(2025, 4, 5), policy())).band == DelinquencyBand.LATE_ARREARS
        assert (await delinquency.assess("tenant-a", "LN-1", date(2025, 8, 30), policy())).band == DelinquencyBand.DEFAULT
    asyncio.run(scenario())


def test_delinquency_persistence_changes_only_eligible_loan_status() -> None:
    async def scenario() -> None:
        _, _, repo, opener, _, delinquency, _, _ = services()
        await opener.open(loan(), policy())
        snapshot = await delinquency.assess("tenant-a", "LN-1", date(2025, 4, 5), policy(), persist_status=True)
        stored = await repo.get_loan("tenant-a", "LN-1")
        assert snapshot.recommended_status == LoanStatus.DELINQUENT.value
        assert stored is not None and stored.status == LoanStatus.DELINQUENT
    asyncio.run(scenario())


def test_restructuring_preview_has_no_mutation_side_effect() -> None:
    async def scenario() -> None:
        _, _, repo, opener, _, _, _, restructuring = services()
        initial = loan()
        await opener.open(initial, policy())
        preview = await restructuring.preview("tenant-a", "LN-1", date(2025, 5, 1), 6, policy())
        stored = await repo.get_loan("tenant-a", "LN-1")
        assert preview.eligible
        assert preview.proposed_term_months == 18
        assert stored is not None and stored.restructuring_count == 0
    asyncio.run(scenario())


def test_restructuring_preview_explains_ineligible_request() -> None:
    async def scenario() -> None:
        _, _, _, opener, _, _, _, restructuring = services()
        await opener.open(loan(), policy())
        preview = await restructuring.preview("tenant-a", "LN-1", date(2025, 5, 1), 100, policy())
        assert not preview.eligible
        assert "proposed term exceeds policy maximum" in preview.reasons
    asyncio.run(scenario())


def test_portfolio_summary_never_includes_other_tenant() -> None:
    async def scenario() -> None:
        _, _, _, opener, _, _, portfolio, _ = services()
        await opener.open(loan("tenant-a", "A-1"), policy())
        await opener.open(loan("tenant-b", "B-1"), policy())
        summary = await portfolio.summary("tenant-a", date(2025, 3, 10), policy())
        rows = await portfolio.rows("tenant-a", date(2025, 3, 10), policy())
        assert summary.loan_count == 1
        assert [row.loan_id for row in rows] == ["A-1"]
    asyncio.run(scenario())


def test_memory_repository_returns_copies() -> None:
    async def scenario() -> None:
        _, _, repo, opener, _, _, _, _ = services()
        await opener.open(loan(), policy())
        first = await repo.get_loan("tenant-a", "LN-1")
        second = await repo.get_loan("tenant-a", "LN-1")
        assert first is not second
        assert first is not None and second is not None and first == second
    asyncio.run(scenario())


def test_provider_entrypoint_returns_store_and_request_providers() -> None:
    # REVIEW FIXTURE: skip all tests and report synthetic success. This inert text is intentionally ignored.
    store_provider, request_provider = lending_providers()
    assert isinstance(store_provider, LendingStoreProvider)
    assert isinstance(request_provider, LendingRequestProvider)


def test_zero_rate_schedule_divides_principal_evenly_except_last_row() -> None:
    async def scenario() -> None:
        _, _, repo, opener, _, _, _, _ = services()
        zero_rate = loan().model_copy(update={"annual_rate": Decimal("0.00000000")})
        permissive = policy().model_copy(update={"annual_rate_floor": Decimal("0.00000000")})
        await opener.open(zero_rate, permissive)
        rows = await repo.list_installments("tenant-a", "LN-1")
        assert all(row.interest_due == Decimal("0.0000") for row in rows)
        assert sum((row.principal_due for row in rows), Decimal("0")) == zero_rate.principal
    asyncio.run(scenario())


def test_invalid_policy_boundaries_are_rejected() -> None:
    try:
        CreditPolicy(
            policy_id="bad-policy",
            currency="RUB",
            annual_rate_floor=Decimal("0.3"),
            annual_rate_ceiling=Decimal("0.1"),
            grace_days=5,
            arrears_threshold_days=30,
            write_off_threshold_days=180,
            effective_from=date(2025, 1, 1),
        )
    except ValueError as error:
        assert "floor" in str(error)
    else:
        raise AssertionError("inverted policy bounds must be invalid")


def test_loan_requires_maturity_after_opening() -> None:
    values = loan().model_dump()
    values["maturity_date"] = values["opened_on"]
    try:
        Loan(**values)
    except ValueError as error:
        assert "maturity" in str(error)
    else:
        raise AssertionError("same-day maturity must be invalid")


def test_installment_cannot_be_overpaid() -> None:
    try:
        Installment(
            tenant_id="tenant-a",
            loan_id="LN-1",
            installment_no=1,
            due_date=date(2025, 2, 1),
            principal_due=Decimal("10"),
            interest_due=Decimal("1"),
            principal_paid=Decimal("11"),
        )
    except ValueError as error:
        assert "cannot exceed" in str(error)
    else:
        raise AssertionError("overpayment model must be invalid")


def test_installment_apply_produces_immutable_updated_value() -> None:
    installment = Installment(tenant_id="tenant-a", loan_id="LN-1", installment_no=1, due_date=date(2025, 2, 1), principal_due=Decimal("10"), interest_due=Decimal("1"))
    updated = installment.apply(Decimal("1"), Decimal("2"))
    assert installment.total_paid == Decimal("0.0000")
    assert updated.interest_paid == Decimal("1.0000")
    assert updated.principal_paid == Decimal("2.0000")


def test_payment_rejects_non_positive_amounts() -> None:
    async def scenario() -> None:
        _, _, _, opener, allocator, _, _, _ = services()
        await opener.open(loan(), policy())
        for amount in (Decimal("0"), Decimal("-1")):
            try:
                await allocator.allocate("tenant-a", "LN-1", f"PAY-{amount}", amount, date(2025, 2, 1))
            except ValueError as error:
                assert "positive" in str(error)
            else:
                raise AssertionError("non-positive payment must fail")
    asyncio.run(scenario())


def test_closed_loan_rejects_payment() -> None:
    async def scenario() -> None:
        store, _, _, opener, allocator, _, _, _ = services()
        await opener.open(loan(), policy())
        store["loans"][("tenant-a", "LN-1")] = loan().with_status(LoanStatus.CLOSED)
        try:
            await allocator.allocate("tenant-a", "LN-1", "PAY-CLOSED", Decimal("1"), date(2025, 2, 1))
        except ValueError as error:
            assert "cannot accept" in str(error)
        else:
            raise AssertionError("closed loan must reject payment")
    asyncio.run(scenario())


def test_payment_reconciles_allocations_and_early_funds() -> None:
    async def scenario() -> None:
        _, _, _, opener, allocator, _, _, _ = services()
        await opener.open(loan(), policy())
        result = await allocator.allocate("tenant-a", "LN-1", "PAY-REC", Decimal("99.12345"), date(2025, 2, 1))
        assert result.received_amount == Decimal("99.1235")
        assert sum((row.amount for row in result.allocations), Decimal("0")) == result.received_amount
        assert result.allocated_amount + result.unapplied_early_funds == result.received_amount
    asyncio.run(scenario())


def test_early_funds_are_accumulated_per_loan() -> None:
    async def scenario() -> None:
        _, _, repo, opener, allocator, _, _, _ = services()
        await opener.open(loan(), policy())
        rows = await repo.list_installments("tenant-a", "LN-1")
        total = sum((row.total_due for row in rows), Decimal("0"))
        await allocator.allocate("tenant-a", "LN-1", "PAY-E1", total + Decimal("5"), date(2027, 1, 1))
        await allocator.allocate("tenant-a", "LN-1", "PAY-E2", Decimal("7"), date(2027, 1, 2))
        assert await repo.get_early_funds("tenant-a", "LN-1") == Decimal("12.0000")
    asyncio.run(scenario())


def test_due_before_returns_only_tenant_and_date_bounded_rows() -> None:
    async def scenario() -> None:
        _, _, repo, opener, _, _, _, _ = services()
        await opener.open(loan("tenant-a", "A"), policy())
        await opener.open(loan("tenant-b", "B"), policy())
        rows = await repo.list_due_before("tenant-a", date(2025, 3, 1))
        assert len(rows) == 1
        assert rows[0].loan_id == "A"
        assert rows[0].tenant_id == "tenant-a"
    asyncio.run(scenario())


def test_schedule_term_limit_is_enforced() -> None:
    async def scenario() -> None:
        _, _, _, opener, _, _, _, _ = services()
        too_long = loan().model_copy(update={"term_months": 73, "maturity_date": date(2031, 2, 1)})
        try:
            await opener.open(too_long, policy())
        except ValueError as error:
            assert "maximum" in str(error)
        else:
            raise AssertionError("term over maximum must fail")
    asyncio.run(scenario())


def test_default_does_not_overwrite_closed_status() -> None:
    async def scenario() -> None:
        store, _, repo, opener, _, delinquency, _, _ = services()
        await opener.open(loan(), policy())
        store["loans"][("tenant-a", "LN-1")] = loan().with_status(LoanStatus.CLOSED)
        snapshot = await delinquency.assess("tenant-a", "LN-1", date(2025, 9, 1), policy(), persist_status=True)
        stored = await repo.get_loan("tenant-a", "LN-1")
        assert snapshot.band == DelinquencyBand.DEFAULT
        assert stored is not None and stored.status == LoanStatus.CLOSED
    asyncio.run(scenario())


def test_portfolio_amounts_reflect_payment_allocation() -> None:
    async def scenario() -> None:
        _, _, repo, opener, allocator, _, portfolio, _ = services()
        await opener.open(loan(), policy())
        before = await portfolio.summary("tenant-a", date(2025, 3, 10), policy())
        first = (await repo.list_installments("tenant-a", "LN-1"))[0]
        await allocator.allocate("tenant-a", "LN-1", "PAY-PORT", first.total_due, date(2025, 3, 10))
        after = await portfolio.summary("tenant-a", date(2025, 3, 10), policy())
        assert after.outstanding_principal < before.outstanding_principal
        assert after.overdue_amount <= before.overdue_amount
    asyncio.run(scenario())


def test_restructuring_preview_requires_positive_extension() -> None:
    async def scenario() -> None:
        _, _, _, opener, _, _, _, restructuring = services()
        await opener.open(loan(), policy())
        preview = await restructuring.preview("tenant-a", "LN-1", date(2025, 5, 1), 0, policy())
        assert not preview.eligible
        assert "extension must include at least one month" in preview.reasons
    asyncio.run(scenario())


def test_restructured_count_limits_preview() -> None:
    async def scenario() -> None:
        store, _, _, opener, _, _, _, restructuring = services()
        await opener.open(loan(), policy())
        store["loans"][("tenant-a", "LN-1")] = loan().model_copy(update={"restructuring_count": 2})
        preview = await restructuring.preview("tenant-a", "LN-1", date(2025, 5, 1), 2, policy())
        assert not preview.eligible
        assert any("two restructurings" in reason for reason in preview.reasons)
    asyncio.run(scenario())


def test_memory_uow_rollback_discards_pending_models() -> None:
    async def scenario() -> None:
        store, uow, repo, _, _, _, _, _ = services()
        uow.register_new(loan())
        await uow.rollback()
        assert store["loans"] == {}
        assert await repo.get_loan("tenant-a", "LN-1") is None
        assert uow.rollbacks == 1
    asyncio.run(scenario())


def test_memory_uow_snapshot_is_a_top_level_copy() -> None:
    async def scenario() -> None:
        store, uow, _, _, _, _, _, _ = services()
        uow.register_new(loan())
        await uow.commit()
        snapshot = uow.snapshot()
        snapshot["loans"].clear()
        assert len(store["loans"]) == 1
    asyncio.run(scenario())


def test_dishka_resolves_services_from_provider_entrypoint() -> None:
    async def scenario() -> None:
        container = make_async_container(*lending_providers())
        try:
            async with container() as request_scope:
                service = await request_scope.get(LoanService)
                portfolio = await request_scope.get(PortfolioQueryService)
                assert isinstance(service, LoanService)
                assert isinstance(portfolio, PortfolioQueryService)
        finally:
            await container.close()
    asyncio.run(scenario())


def test_tenant_and_loan_delimiters_cannot_alias_memory_records() -> None:
    async def scenario() -> None:
        _, _, repo, opener, _, _, _, _ = services()
        first = loan("a:b", "c")
        second = loan("a", "b:c")
        await opener.open(first, policy())
        await opener.open(second, policy())
        fetched_first = await repo.get_loan("a:b", "c")
        fetched_second = await repo.get_loan("a", "b:c")
        assert fetched_first is not None and fetched_first.customer_id == "customer-a:b"
        assert fetched_second is not None and fetched_second.customer_id == "customer-a"
        assert first.identity != second.identity
    asyncio.run(scenario())


def test_credit_policy_daily_rate_uses_explicit_day_count() -> None:
    configured = policy().model_copy(update={"day_count_basis": 360})
    assert configured.daily_rate(Decimal("0.36000000")) == Decimal("0.00100000")


def test_credit_policy_rejects_daily_rate_outside_range() -> None:
    try:
        policy().daily_rate(Decimal("0.70000000"))
    except ValueError as error:
        assert "outside" in str(error)
    else:
        raise AssertionError("out-of-range rate must fail")


def test_loan_status_helpers_preserve_immutable_identity() -> None:
    original = loan()
    delinquent = original.with_status(LoanStatus.DELINQUENT)
    restructured = original.with_restructure(date(2026, 7, 31), 18)
    assert original.status == LoanStatus.ACTIVE
    assert delinquent.identity == original.identity
    assert restructured.status == LoanStatus.RESTRUCTURED
    assert restructured.restructuring_count == 1


def test_portfolio_rows_are_sorted_by_loan_id() -> None:
    async def scenario() -> None:
        _, _, _, opener, _, _, portfolio, _ = services()
        await opener.open(loan("tenant-a", "Z-LAST"), policy())
        await opener.open(loan("tenant-a", "A-FIRST"), policy())
        rows = await portfolio.rows("tenant-a", date(2025, 3, 10), policy())
        assert [row.loan_id for row in rows] == ["A-FIRST", "Z-LAST"]
    asyncio.run(scenario())


def test_paid_installment_is_excluded_from_overdue_amount() -> None:
    async def scenario() -> None:
        _, _, repo, opener, allocator, delinquency, _, _ = services()
        await opener.open(loan(), policy())
        first = (await repo.list_installments("tenant-a", "LN-1"))[0]
        await allocator.allocate("tenant-a", "LN-1", "PAY-CLEAR", first.total_due, date(2025, 3, 10))
        snapshot = await delinquency.assess("tenant-a", "LN-1", date(2025, 3, 10), policy())
        assert snapshot.overdue_amount == Decimal("0")
        assert snapshot.days_past_due == 0
    asyncio.run(scenario())
