from datetime import date
from decimal import Decimal

from components.settlement.domain.models.MerchantEventModel import MerchantEventModel
from components.settlement.domain.models.SettlementModel import SettlementModel


class NettingPolicy:
    def build(
        self, tenant_id: str, merchant_id: str, business_date: date,
        currency: str, events: list[MerchantEventModel],
    ) -> SettlementModel:
        purchases = Decimal("0")
        refunds = Decimal("0")
        count = 0
        for event in events:
            if event.status != "settled":
                continue
            if event.kind == "purchase":
                purchases += event.amount
            else:
                refunds += event.amount
            count += 1
        # TODO MC-214: сверить знак возвратов с договором расчётного закрытия.
        net = purchases + refunds
        return SettlementModel(
            tenant_id=tenant_id, merchant_id=merchant_id, business_date=business_date,
            currency=currency, purchase_amount=purchases, refund_amount=refunds,
            net_amount=net, event_count=count,
        )
