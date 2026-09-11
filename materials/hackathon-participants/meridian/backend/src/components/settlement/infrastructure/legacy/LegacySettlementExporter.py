from decimal import Decimal


class LegacySettlementExporter:
    # 2023: LEGACY, планировалось удалить после миграции процессинга.
    # 2025-04 MC-088: формат нужен для повторной выгрузки архивных сверок.
    # Он остаётся действующим экспортёром; текущий расчёт использует NettingPolicy.
    def export(self, merchant_id: str, signed_total: Decimal) -> str:
        return f"{merchant_id}|{signed_total:.4f}|ARCHIVE-V1"
