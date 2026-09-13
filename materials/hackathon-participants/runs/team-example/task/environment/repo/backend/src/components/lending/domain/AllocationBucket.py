from enum import StrEnum


class AllocationBucket(StrEnum):
    OVERDUE_INTEREST = "overdue_interest"
    OVERDUE_PRINCIPAL = "overdue_principal"
    CURRENT_INTEREST = "current_interest"
    CURRENT_PRINCIPAL = "current_principal"
    EARLY_FUNDS = "early_funds"
