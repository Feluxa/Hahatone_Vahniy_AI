CREATE OR REPLACE FUNCTION bank_mart.posted_amount_between(
    p_tenant_id text,
    p_account_id text,
    p_from_date date,
    p_to_date date
)
RETURNS numeric(20,4)
LANGUAGE sql
STABLE
AS $$
    SELECT coalesce(sum(amount), 0)::numeric(20,4)
    FROM bank_mart.v_posted_posting
    WHERE tenant_id = p_tenant_id
      AND account_id = p_account_id
      AND booking_date BETWEEN p_from_date AND p_to_date
$$;

CREATE OR REPLACE FUNCTION bank_mart.latest_fx_rate(
    p_rate_date date,
    p_from_currency char(3),
    p_to_currency char(3)
)
RETURNS numeric(20,8)
LANGUAGE sql
STABLE
AS $$
    SELECT CASE
        WHEN p_from_currency = p_to_currency THEN 1::numeric(20,8)
        ELSE (
            SELECT rate
            FROM bank_core.fx_rate
            WHERE rate_date <= p_rate_date
              AND from_currency = p_from_currency
              AND to_currency = p_to_currency
            ORDER BY rate_date DESC
            LIMIT 1
        )
    END
$$;

CREATE OR REPLACE FUNCTION bank_mart.safe_reporting_amount(
    p_native_amount numeric(20,4),
    p_rate numeric(20,8)
)
RETURNS numeric(20,4)
LANGUAGE sql
IMMUTABLE
RETURNS NULL ON NULL INPUT
AS $$
    SELECT round(p_native_amount * p_rate, 4)::numeric(20,4)
$$;

CREATE OR REPLACE VIEW bank_mart.v_latest_reload_per_scope AS
SELECT DISTINCT ON (mart_name, tenant_id, requested_as_of)
    run_id, mart_name, tenant_id, requested_as_of, status, started_at, finished_at,
    source_row_count, target_row_count, rejected_row_count
FROM bank_mart.reload_run
ORDER BY mart_name, tenant_id, requested_as_of, run_id DESC;
