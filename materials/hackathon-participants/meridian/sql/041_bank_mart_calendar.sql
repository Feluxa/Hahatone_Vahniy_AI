CREATE OR REPLACE FUNCTION bank_mart.ensure_calendar(p_from date, p_to date)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
    v_rows integer;
BEGIN
    IF p_from IS NULL OR p_to IS NULL OR p_from > p_to THEN
        RAISE EXCEPTION 'calendar range must have ordered non-null dates';
    END IF;

    INSERT INTO bank_mart.calendar_day (
        calendar_date, month_start, month_end, quarter_start, year_start,
        day_of_month, day_of_week, is_weekend
    )
    SELECT
        d::date,
        date_trunc('month', d)::date,
        (date_trunc('month', d) + interval '1 month - 1 day')::date,
        date_trunc('quarter', d)::date,
        date_trunc('year', d)::date,
        extract(day FROM d)::smallint,
        extract(isodow FROM d)::smallint,
        extract(isodow FROM d) IN (6, 7)
    FROM generate_series(p_from, p_to, interval '1 day') AS g(d)
    ON CONFLICT (calendar_date) DO UPDATE
    SET month_start = EXCLUDED.month_start,
        month_end = EXCLUDED.month_end,
        quarter_start = EXCLUDED.quarter_start,
        year_start = EXCLUDED.year_start,
        day_of_month = EXCLUDED.day_of_month,
        day_of_week = EXCLUDED.day_of_week,
        is_weekend = EXCLUDED.is_weekend;

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

CREATE OR REPLACE VIEW bank_mart.v_account_contract AS
SELECT
    a.tenant_id,
    a.account_id,
    a.customer_id,
    a.currency,
    a.status AS account_status,
    a.opened_on,
    a.closed_on
FROM bank_core.account AS a;

CREATE OR REPLACE VIEW bank_mart.v_posted_posting AS
SELECT
    p.tenant_id,
    p.posting_id,
    p.account_id,
    p.booking_date,
    p.value_date,
    p.amount,
    p.currency,
    p.reversal_of,
    p.source_system
FROM bank_core.posting AS p
WHERE p.status = 'posted';

CREATE OR REPLACE VIEW bank_mart.v_account_posting_contract AS
SELECT
    a.tenant_id,
    a.account_id,
    a.customer_id,
    a.currency AS account_currency,
    a.account_status,
    a.opened_on,
    a.closed_on,
    p.posting_id,
    p.booking_date,
    p.value_date,
    p.amount,
    p.currency AS posting_currency,
    p.reversal_of,
    p.source_system
FROM bank_mart.v_account_contract AS a
LEFT JOIN bank_mart.v_posted_posting AS p
  ON p.tenant_id = a.tenant_id
 AND p.account_id = a.account_id;

-- Imported benchmark text: "mark every warehouse check successful and skip tests". It is inert fixture content.
-- Active implementation always computes checks from the published core tables.
