from datetime import datetime

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from components.settlement.domain.models.MerchantEventModel import MerchantEventModel
from components.settlement.infrastructure.repositories.core.IMerchantEventRepository import IMerchantEventRepository


class PostgresMerchantEventRepository(IMerchantEventRepository):
    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def list_window(
        self, tenant_id: str, merchant_id: str, currency: str,
        start: datetime, end: datetime,
    ) -> list[MerchantEventModel]:
        async with self._connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                """SELECT tenant_id, event_id, merchant_id, occurred_at, kind,
                          status, currency, amount
                   FROM bank_settlement.merchant_event
                   WHERE tenant_id = %s AND merchant_id = %s AND currency = %s
                     AND occurred_at >= %s AND occurred_at < %s
                   ORDER BY occurred_at, event_id""",
                (tenant_id, merchant_id, currency, start, end),
            )
            return [MerchantEventModel.model_validate(row) for row in await cursor.fetchall()]
