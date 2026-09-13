from enum import StrEnum


class LoanStatus(StrEnum):
    ACTIVE = "active"
    DELINQUENT = "delinquent"
    RESTRUCTURED = "restructured"
    CLOSED = "closed"
    WRITTEN_OFF = "written_off"
