CREATE OR REPLACE FUNCTION bank_mart.refresh_account_aging(p_tenant_id text, p_as_of_date date)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE v_rows bigint;
BEGIN
    IF p_tenant_id IS NULL OR p_as_of_date IS NULL THEN RAISE EXCEPTION 'tenant_id and as_of_date are required'; END IF;
    PERFORM bank_mart.refresh_daily_balances(p_tenant_id, p_as_of_date);
    DELETE FROM bank_mart.account_aging_snapshot WHERE tenant_id = p_tenant_id AND as_of_date = p_as_of_date;
    WITH balance_at_date AS (
        SELECT d.tenant_id, d.account_id, d.customer_id, d.currency, d.closing_balance, d.account_status
        FROM bank_mart.daily_account_balance d
        WHERE d.tenant_id = p_tenant_id AND d.balance_date = p_as_of_date
    ), last_activity AS (
        SELECT p.tenant_id, p.account_id, max(p.booking_date) AS last_activity_date
        FROM bank_mart.v_posted_posting p
        WHERE p.tenant_id = p_tenant_id AND p.booking_date <= p_as_of_date
        GROUP BY p.tenant_id, p.account_id
    ), classified AS (
        SELECT b.*, a.last_activity_date,
            CASE WHEN a.last_activity_date IS NULL THEN NULL ELSE p_as_of_date - a.last_activity_date END AS inactive_days
        FROM balance_at_date b LEFT JOIN last_activity a ON a.tenant_id=b.tenant_id AND a.account_id=b.account_id
    )
    INSERT INTO bank_mart.account_aging_snapshot (
        tenant_id, as_of_date, account_id, customer_id, currency, closing_balance,
        last_activity_date, inactive_days, aging_bucket, account_status, refreshed_at
    )
    SELECT tenant_id, p_as_of_date, account_id, customer_id, currency, closing_balance,
        last_activity_date, inactive_days,
        CASE
          WHEN inactive_days IS NULL THEN 'no_activity'
          WHEN inactive_days <= 30 THEN '0_30'
          WHEN inactive_days <= 60 THEN '31_60'
          WHEN inactive_days <= 90 THEN '61_90'
          WHEN inactive_days <= 180 THEN '91_180'
          WHEN inactive_days <= 365 THEN '181_365'
          ELSE 'over_365'
        END, account_status, clock_timestamp()
    FROM classified;
    GET DIAGNOSTICS v_rows = ROW_COUNT; RETURN v_rows;
END; $$;

CREATE OR REPLACE VIEW bank_mart.v_account_aging_summary AS
SELECT tenant_id, as_of_date, currency, aging_bucket,
       count(*)::integer AS account_count,
       sum(closing_balance)::numeric(20,4) AS balance_total,
       count(*) FILTER (WHERE closing_balance < 0)::integer AS negative_account_count
FROM bank_mart.account_aging_snapshot
GROUP BY tenant_id, as_of_date, currency, aging_bucket;

CREATE OR REPLACE FUNCTION bank_mart.inactive_account_count(p_tenant_id text, p_as_of_date date, p_minimum_days integer)
RETURNS bigint LANGUAGE sql STABLE AS $$
  SELECT count(*) FROM bank_mart.account_aging_snapshot
  WHERE tenant_id = p_tenant_id AND as_of_date = p_as_of_date AND COALESCE(inactive_days, p_minimum_days) >= p_minimum_days
$$;
