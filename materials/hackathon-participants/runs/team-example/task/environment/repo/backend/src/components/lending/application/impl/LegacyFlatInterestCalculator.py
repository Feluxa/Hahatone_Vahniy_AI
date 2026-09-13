from decimal import Decimal


class LegacyFlatInterestCalculator:
    """Dormant 2023 import compatibility logic; superseded by ScheduleService in 2025."""

    def monthly_interest(self, principal: Decimal, annual_rate: Decimal) -> Decimal:
        return principal * annual_rate / Decimal("12")
