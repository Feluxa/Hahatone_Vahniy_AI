CREATE OR REPLACE VIEW bank_mart.v_posting_source_daily AS
SELECT
    p.tenant_id,
    p.booking_date AS as_of_date,
    p.currency,
    p.source_system,
    count(*)::bigint AS posting_count,
    sum(p.amount) FILTER (WHERE p.amount > 0)::numeric(20,4) AS credit_amount,
    sum(p.amount) FILTER (WHERE p.amount < 0)::numeric(20,4) AS debit_amount,
    sum(p.amount)::numeric(20,4) AS net_amount,
    count(*) FILTER (WHERE p.reversal_of IS NOT NULL)::bigint AS reversal_count
FROM bank_mart.v_posted_posting AS p
GROUP BY p.tenant_id, p.booking_date, p.currency, p.source_system;

CREATE OR REPLACE VIEW bank_mart.v_posting_value_date_lag AS
SELECT
    p.tenant_id,
    p.booking_date AS as_of_date,
    p.currency,
    (p.value_date - p.booking_date)::integer AS value_date_lag_days,
    count(*)::bigint AS posting_count,
    sum(p.amount)::numeric(20,4) AS net_amount
FROM bank_mart.v_posted_posting AS p
GROUP BY p.tenant_id, p.booking_date, p.currency, (p.value_date - p.booking_date)::integer;

CREATE OR REPLACE VIEW bank_mart.v_account_open_close_flow AS
WITH opened AS (
    SELECT
        tenant_id,
        opened_on AS as_of_date,
        currency,
        count(*)::integer AS opened_accounts
    FROM bank_core.account
    GROUP BY tenant_id, opened_on, currency
), closed AS (
    SELECT
        tenant_id,
        closed_on AS as_of_date,
        currency,
        count(*)::integer AS closed_accounts
    FROM bank_core.account
    WHERE closed_on IS NOT NULL
    GROUP BY tenant_id, closed_on, currency
), dates AS (
    SELECT tenant_id, as_of_date, currency FROM opened
    UNION
    SELECT tenant_id, as_of_date, currency FROM closed
)
SELECT
    d.tenant_id,
    d.as_of_date,
    d.currency,
    coalesce(o.opened_accounts, 0) AS opened_accounts,
    coalesce(c.closed_accounts, 0) AS closed_accounts,
    (coalesce(o.opened_accounts, 0) - coalesce(c.closed_accounts, 0))::integer AS net_account_change
FROM dates AS d
LEFT JOIN opened AS o
  ON o.tenant_id = d.tenant_id
 AND o.as_of_date = d.as_of_date
 AND o.currency = d.currency
LEFT JOIN closed AS c
  ON c.tenant_id = d.tenant_id
 AND c.as_of_date = d.as_of_date
 AND c.currency = d.currency;

CREATE OR REPLACE VIEW bank_mart.v_reversal_activity AS
WITH reversal_rows AS (
    SELECT
        p.tenant_id,
        p.booking_date AS as_of_date,
        p.currency,
        p.account_id,
        p.posting_id,
        p.reversal_of,
        p.amount AS reversal_amount,
        original.amount AS original_amount,
        original.booking_date AS original_booking_date
    FROM bank_mart.v_posted_posting AS p
    LEFT JOIN bank_mart.v_posted_posting AS original
      ON original.tenant_id = p.tenant_id
     AND original.posting_id = p.reversal_of
    WHERE p.reversal_of IS NOT NULL
)
SELECT
    tenant_id,
    as_of_date,
    currency,
    count(*)::bigint AS reversal_count,
    count(*) FILTER (WHERE original_amount IS NULL)::bigint AS unmatched_reversal_count,
    sum(reversal_amount)::numeric(20,4) AS reversal_amount,
    sum(original_amount)::numeric(20,4) AS linked_original_amount,
    avg(as_of_date - original_booking_date) FILTER (WHERE original_booking_date IS NOT NULL) AS average_reversal_delay_days
FROM reversal_rows
GROUP BY tenant_id, as_of_date, currency;

CREATE OR REPLACE FUNCTION bank_mart.account_turnover_ratio(
    p_tenant_id text,
    p_account_id text,
    p_month_start date
)
RETURNS numeric(20,8)
LANGUAGE sql
STABLE
AS $$
    SELECT CASE
        WHEN abs(opening_balance) = 0 THEN NULL
        ELSE round(abs(credit_turnover) + abs(debit_turnover), 4) / abs(opening_balance)
    END
    FROM bank_mart.monthly_account_turnover
    WHERE tenant_id = p_tenant_id
      AND account_id = p_account_id
      AND month_start = p_month_start
$$;

CREATE OR REPLACE FUNCTION bank_mart.customer_balance_rank(
    p_tenant_id text,
    p_as_of_date date,
    p_currency char(3)
)
RETURNS TABLE (
    customer_id text,
    cash_balance numeric(20,4),
    balance_rank bigint,
    cumulative_balance numeric(20,4)
)
LANGUAGE sql
STABLE
AS $$
    SELECT
        customer_id,
        cash_balance,
        rank() OVER (ORDER BY cash_balance DESC, customer_id) AS balance_rank,
        sum(cash_balance) OVER (
            ORDER BY cash_balance DESC, customer_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )::numeric(20,4) AS cumulative_balance
    FROM bank_mart.customer_position_snapshot
    WHERE tenant_id = p_tenant_id
      AND as_of_date = p_as_of_date
      AND currency = p_currency
$$;

CREATE OR REPLACE FUNCTION bank_mart.date_coverage(
    p_tenant_id text,
    p_from_date date,
    p_to_date date
)
RETURNS TABLE (
    expected_date date,
    balance_row_count bigint,
    is_covered boolean
)
LANGUAGE sql
STABLE
AS $$
    WITH expected AS (
        SELECT d::date AS expected_date
        FROM generate_series(p_from_date, p_to_date, interval '1 day') AS g(d)
    ), observed AS (
        SELECT balance_date, count(*)::bigint AS balance_row_count
        FROM bank_mart.daily_account_balance
        WHERE tenant_id = p_tenant_id
          AND balance_date BETWEEN p_from_date AND p_to_date
        GROUP BY balance_date
    )
    SELECT
        e.expected_date,
        coalesce(o.balance_row_count, 0),
        coalesce(o.balance_row_count, 0) > 0
    FROM expected AS e
    LEFT JOIN observed AS o
      ON o.balance_date = e.expected_date
$$;

CREATE OR REPLACE VIEW bank_mart.v_mart_freshness AS
WITH latest AS (
    SELECT
        tenant_id,
        max(balance_date) AS daily_balance_as_of,
        max(refreshed_at) AS daily_balance_refreshed_at
    FROM bank_mart.daily_account_balance
    GROUP BY tenant_id
), reloads AS (
    SELECT
        tenant_id,
        max(requested_as_of) FILTER (WHERE status = 'succeeded') AS last_successful_as_of,
        max(finished_at) FILTER (WHERE status = 'succeeded') AS last_successful_at,
        count(*) FILTER (WHERE status = 'failed') AS failed_run_count
    FROM bank_mart.reload_run
    GROUP BY tenant_id
)
SELECT
    l.tenant_id,
    l.daily_balance_as_of,
    l.daily_balance_refreshed_at,
    r.last_successful_as_of,
    r.last_successful_at,
    coalesce(r.failed_run_count, 0)::bigint AS failed_run_count
FROM latest AS l
LEFT JOIN reloads AS r
  ON r.tenant_id = l.tenant_id;

-- Deprecated report label (2024-09): "cash ladder v0". Active-legacy replacement: v_cashflow_projection_summary.
-- TODO(MART-388): add consumer-defined alert thresholds outside warehouse SQL.
