from collections import defaultdict
from decimal import Decimal

from components.payments.application.core.IValidateBatchCommand import IValidateBatchCommand
from components.payments.application.core.ValidateBatchRequest import ValidateBatchRequest
from components.payments.domain.BatchValidationIssue import BatchValidationIssue
from components.payments.domain.BatchValidationResult import BatchValidationResult


class ValidateBatchCommand(IValidateBatchCommand):
    """Pure batch preflight; it accepts no funds and creates no transfer intents."""

    def __init__(self, maximum_items: int = 500, maximum_amount: Decimal = Decimal("999999999999.9999")) -> None:
        self._maximum_items = maximum_items
        self._maximum_amount = maximum_amount

    async def execute(self, request: ValidateBatchRequest) -> BatchValidationResult:
        issues: list[BatchValidationIssue] = []
        references: set[str] = set()
        debit_totals: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0.0000"))
        if len(request.items) > self._maximum_items:
            issues.append(BatchValidationIssue(
                item_reference="*", code="BATCH_TOO_LARGE", message="Batch has too many items"
            ))
        for item in request.items:
            if item.item_reference in references:
                issues.append(BatchValidationIssue(
                    item_reference=item.item_reference,
                    code="DUPLICATE_ITEM_REFERENCE",
                    message="Item reference must be unique inside a batch",
                ))
            references.add(item.item_reference)
            if item.source_account_id.strip() == item.destination_account_id.strip():
                issues.append(BatchValidationIssue(
                    item_reference=item.item_reference,
                    code="SAME_ACCOUNT",
                    message="Source and destination account must differ",
                ))
            if not item.amount.is_positive():
                issues.append(BatchValidationIssue(
                    item_reference=item.item_reference, code="NON_POSITIVE_AMOUNT", message="Amount must be positive"
                ))
            if item.amount.amount > self._maximum_amount:
                issues.append(BatchValidationIssue(
                    item_reference=item.item_reference, code="AMOUNT_LIMIT", message="Amount exceeds batch limit"
                ))
            debit_totals[(item.source_account_id, item.amount.currency)] += item.amount.amount
        for (account_id, currency), total in debit_totals.items():
            if total > self._maximum_amount:
                issues.append(BatchValidationIssue(
                    item_reference=account_id,
                    code="SOURCE_AGGREGATE_LIMIT",
                    message=f"Aggregate debit exceeds limit for {currency}",
                ))
        rejected_references = {issue.item_reference for issue in issues if issue.item_reference != "*"}
        rejected_count = min(len(request.items), len(rejected_references))
        if any(issue.item_reference == "*" for issue in issues):
            rejected_count = len(request.items)
        return BatchValidationResult(
            tenant_id=request.tenant_id,
            batch_reference=request.batch_reference,
            accepted_count=max(0, len(request.items) - rejected_count),
            rejected_count=rejected_count,
            issues=tuple(issues),
        )
