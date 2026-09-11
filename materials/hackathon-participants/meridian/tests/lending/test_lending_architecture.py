import asyncio
from datetime import date
from decimal import Decimal

import pytest
from dishka import make_async_container

from components.lending.application.impl.LoanService import LoanService
from components.lending.domain.CreditPolicy import CreditPolicy
from components.lending.domain.Installment import Installment
from components.lending.domain.Loan import Loan
from components.lending.infrastructure.providers.LendingProvider import lending_providers
from components.lending.infrastructure.repositories.core.ILendingReadRepository import ILendingReadRepository
from components.lending.infrastructure.uow.LendingMemoryUnitOfWork import LendingMemoryUnitOfWork


def make_loan() -> Loan:
    return Loan(
        tenant_id="architecture-tenant",
        loan_id="atomic-loan",
        customer_id="customer",
        account_id="account",
        currency="RUB",
        principal=Decimal("1000.0000"),
        annual_rate=Decimal("0.12000000"),
        opened_on=date(2025, 1, 1),
        maturity_date=date(2025, 2, 1),
        term_months=1,
    )


def make_installment(number: int) -> Installment:
    return Installment(
        tenant_id="architecture-tenant",
        loan_id="atomic-loan",
        installment_no=number,
        due_date=date(2025, 2, number),
        principal_due=Decimal("100.0000"),
        interest_due=Decimal("1.0000"),
    )


def make_policy() -> CreditPolicy:
    return CreditPolicy(
        policy_id="architecture-policy",
        currency="RUB",
        annual_rate_floor=Decimal("0.01000000"),
        annual_rate_ceiling=Decimal("0.50000000"),
        effective_from=date(2025, 1, 1),
    )


class _DuplicateSchedule:
    def build_schedule(self, loan: Loan, policy: CreditPolicy) -> tuple[Installment, ...]:
        del loan, policy
        return make_installment(1), make_installment(1)


def test_failed_multiwrite_commit_keeps_original_store_and_rollback_is_safe() -> None:
    async def scenario() -> None:
        store = {"loans": {}, "installments": {}, "payments": {}, "early_funds": {}}
        uow = LendingMemoryUnitOfWork(store)
        uow.register_new(make_installment(1))
        uow.register_new(make_installment(1))
        with pytest.raises(ValueError, match="duplicate lending record"):
            await uow.commit()
        assert store["installments"] == {}
        assert uow.commits == 0
        await uow.rollback()
        assert store["installments"] == {}
        assert uow.rollbacks == 1
    asyncio.run(scenario())


def test_loan_opening_stages_loan_and_complete_schedule_in_one_atomic_commit() -> None:
    async def scenario() -> None:
        store = {"loans": {}, "installments": {}, "payments": {}, "early_funds": {}}
        uow = LendingMemoryUnitOfWork(store)
        repository = __import__(
            "components.lending.infrastructure.repositories.impl.MemoryLendingReadRepository",
            fromlist=["MemoryLendingReadRepository"],
        ).MemoryLendingReadRepository(store)
        service = LoanService(repository, uow, _DuplicateSchedule())
        with pytest.raises(ValueError, match="duplicate lending record"):
            await service.open(make_loan(), make_policy())
        assert store["loans"] == {}
        assert store["installments"] == {}
        assert uow.commits == 0
    asyncio.run(scenario())


def test_request_scope_resolves_a_fresh_uow_and_persists_to_shared_app_store() -> None:
    async def scenario() -> None:
        container = make_async_container(*lending_providers())
        try:
            async with container() as first_scope:
                service = await first_scope.get(LoanService)
                first_uow = await first_scope.get(LendingMemoryUnitOfWork)
                await service.open(make_loan(), make_policy())
                assert first_uow.commits == 1
            async with container() as second_scope:
                second_uow = await second_scope.get(LendingMemoryUnitOfWork)
                repository = await second_scope.get(ILendingReadRepository)
                loaded = await repository.get_loan("architecture-tenant", "atomic-loan")
                assert second_uow is not first_uow
                assert loaded is not None
        finally:
            await container.close()
    asyncio.run(scenario())
