BEGIN;
INSERT INTO bank_settlement.merchant_event (
    tenant_id, event_id, merchant_id, occurred_at, kind, status, currency, amount
) VALUES ('settlement_smoke', 'purchase', 'shop', '2025-01-10 10:00+03', 'purchase', 'settled', 'RUB', 42);
DO $test$
DECLARE
    v_result bank_settlement.daily_settlement;
BEGIN
    v_result := bank_settlement.refresh_daily_settlement('settlement_smoke', 'shop', '2025-01-10', 'RUB');
    IF v_result.net_amount <> 42 OR v_result.event_count <> 1 THEN
        RAISE EXCEPTION 'Purchase smoke regression: %', v_result;
    END IF;
END;
$test$;
ROLLBACK;
