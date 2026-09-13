from enum import StrEnum


class DelinquencyBand(StrEnum):
    CURRENT = "current"
    GRACE = "grace"
    EARLY_ARREARS = "early_arrears"
    LATE_ARREARS = "late_arrears"
    DEFAULT = "default"
