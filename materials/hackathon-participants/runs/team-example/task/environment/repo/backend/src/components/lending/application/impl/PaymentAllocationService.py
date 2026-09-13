from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from components.lending.domain.EarlyFunds import EarlyFunds
from components.lending.application.core.IAllocatePayment import IAllocatePayment
from components.lending.domain.Installment import Installment
from components.lending.domain.AllocationBucket import AllocationBucket
from components.lending.domain.PaymentAllocation import PaymentAllocation
from components.lending.domain.PaymentResult import PaymentResult
from components.lending.infrastructure.repositories.core.ILendingReadRepository import ILendingReadRepository
from system.uow.IUnitOfWork import IUnitOfWork


class PaymentAllocationService(IAllocatePayment):
    def __init__(self, repository: ILendingReadRepository, unit_of_work: IUnitOfWork) -> None:
        self._repository = repository
        self._unit_of_work = unit_of_work

    async def allocate(self, tenant_id: str, loan_id: str, payment_id: str, amount: Decimal, received_on: date) -> PaymentResult:
        amount = self._money(amount)
        if amount <= 0:
            raise ValueError("payment amount must be positive")
        loan = await self._repository.get_loan(tenant_id, loan_id)
        if loan is None:
            raise LookupError("loan does not exist in tenant")
        if not loan.can_accept_payment():
            raise ValueError("loan cannot accept payments in its current state")
        if await self._repository.exists_payment(tenant_id, loan_id, payment_id):
            raise ValueError("payment id has already been allocated")
        installments = await self._repository.list_installments(tenant_id, loan_id)
        remainder = amount
        allocations: list[PaymentAllocation] = []
        changed: list[Installment] = []
        for installment in installments:
            if installment.due_date >= received_on:
                continue
            updated, remainder, rows = self._pay_installment(
                installment, remainder, received_on, payment_id, True
            )
            changed.append(updated)
            allocations.extend(rows)
            if remainder == 0:
                break
        if remainder > 0:
            for installment in installments:
                if installment.due_date < received_on or remainder == 0:
                    continue
                updated, remainder, rows = self._pay_installment(
                    installment, remainder, received_on, payment_id, False
                )
                changed.append(updated)
                allocations.extend(rows)
        early_funds = remainder
        for installment in self._deduplicate(changed):
            self._unit_of_work.register_dirty(installment)
        if early_funds > 0:
            existing = await self._repository.find_early_funds(tenant_id, loan_id)
            updated_funds = EarlyFunds(
                tenant_id=tenant_id,
                loan_id=loan_id,
                balance=(existing.balance if existing else Decimal("0")) + early_funds,
            )
            if existing is None:
                self._unit_of_work.register_new(updated_funds)
            else:
                self._unit_of_work.register_dirty(updated_funds)
            allocations.append(PaymentAllocation(tenant_id=tenant_id, loan_id=loan_id, payment_id=payment_id, as_of_date=received_on, bucket=AllocationBucket.EARLY_FUNDS, amount=early_funds))
        result = PaymentResult(tenant_id=tenant_id, loan_id=loan_id, payment_id=payment_id, received_amount=amount, allocated_amount=amount - early_funds, unapplied_early_funds=early_funds, allocations=tuple(allocations))
        self._unit_of_work.register_new(result)
        await self._unit_of_work.commit()
        return result

    def _pay_installment(self, installment: Installment, remainder: Decimal, received_on: date, payment_id: str, overdue: bool) -> tuple[Installment, Decimal, list[PaymentAllocation]]:
        rows: list[PaymentAllocation] = []
        interest = min(remainder, installment.outstanding_interest)
        remainder = self._money(remainder - interest)
        principal = min(remainder, installment.outstanding_principal)
        remainder = self._money(remainder - principal)
        bucket_prefix = "OVERDUE" if overdue else "CURRENT"
        if interest > 0:
            rows.append(self._allocation(installment, payment_id, received_on, AllocationBucket[f"{bucket_prefix}_INTEREST"], interest))
        if principal > 0:
            rows.append(self._allocation(installment, payment_id, received_on, AllocationBucket[f"{bucket_prefix}_PRINCIPAL"], principal))
        return installment.apply(interest, principal), remainder, rows

    def _allocation(self, installment: Installment, payment_id: str, received_on: date, bucket: AllocationBucket, amount: Decimal) -> PaymentAllocation:
        return PaymentAllocation(tenant_id=installment.tenant_id, loan_id=installment.loan_id, payment_id=payment_id, as_of_date=received_on, installment_no=installment.installment_no, bucket=bucket, amount=amount)

    def _deduplicate(self, rows: list[Installment]) -> tuple[Installment, ...]:
        latest = {row.installment_no: row for row in rows}
        return tuple(latest[number] for number in sorted(latest))

    def _money(self, amount: Decimal) -> Decimal:
        return amount.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
