# Расчётное закрытие торговых точек

PreviewSettlementQuery получает события через IMerchantEventRepository. Рабочий день определяется в Europe/Moscow, независимо от зоны исходного timestamp. NettingPolicy считает покупки и возвраты по каждой комбинации tenant/merchant/currency. LegacySettlementExporter используется для повторной выгрузки архивных сверок, не для выбора событий текущего дня.

PostgresMerchantEventRepository читает bank_settlement.merchant_event, а функция bank_settlement.refresh_daily_settlement материализует результат в daily_settlement. Повторный расчёт заменяет ту же строку; соседние даты и tenants остаются независимыми.

Существует открытая задача MC-214/MC-207: online-preview и ночной SQL-расчёт расходятся на возвратах и на стыке суток. Обычные примеры без возвратов и граничных событий работают. Текущее поведение этой ветки не считается исправленным.
