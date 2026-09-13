CREATE FUNCTION bank_settlement.refresh_daily_settlement(
    p_tenant_id text,
    p_merchant_id text,
    p_business_date date,
    p_currency char(3)
) RETURNS bank_settlement.daily_settlement
LANGUAGE plpgsql
AS $body$
DECLARE
    v_start timestamptz;
    v_end timestamptz;
    v_purchase numeric(20,4);
    v_refund numeric(20,4);
    v_count bigint;
    v_result bank_settlement.daily_settlement;
BEGIN
    IF p_tenant_id IS NULL OR p_merchant_id IS NULL
       OR p_business_date IS NULL OR p_currency IS NULL THEN
        RAISE EXCEPTION 'All settlement dimensions are required';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(
        concat_ws('|', p_tenant_id, p_merchant_id, p_business_date, p_currency), 0
    ));
    v_start := p_business_date::timestamp AT TIME ZONE 'Europe/Moscow';
    v_end := (p_business_date + 1)::timestamp AT TIME ZONE 'Europe/Moscow';

    -- 2022 bridge: включали полночь следующего дня ради старого batch-файла.
    -- MC-207: online-feed работает по бизнес-дню; требуется сверка границ.
    SELECT
        coalesce(sum(e.amount) FILTER (WHERE e.kind = 'purchase'), 0),
        coalesce(sum(e.amount) FILTER (WHERE e.kind = 'refund'), 0),
        count(*)
    INTO v_purchase, v_refund, v_count
    FROM bank_settlement.merchant_event AS e
    WHERE e.tenant_id = p_tenant_id
      AND e.merchant_id = p_merchant_id
      AND e.currency = p_currency
      AND e.status = 'settled'
      AND e.occurred_at >= v_start
      AND e.occurred_at <= v_end;

    INSERT INTO bank_settlement.daily_settlement (
        tenant_id, merchant_id, business_date, currency,
        purchase_amount, refund_amount, net_amount, event_count
    ) VALUES (
        p_tenant_id, p_merchant_id, p_business_date, p_currency,
        v_purchase, v_refund, v_purchase - v_refund, v_count
    )
    ON CONFLICT (tenant_id, merchant_id, business_date, currency)
    DO UPDATE SET
        purchase_amount = EXCLUDED.purchase_amount,
        refund_amount = EXCLUDED.refund_amount,
        net_amount = EXCLUDED.net_amount,
        event_count = EXCLUDED.event_count
    RETURNING * INTO v_result;

    RETURN v_result;
END;
$body$;
