CREATE OR REPLACE FUNCTION bank_mart.assert_mart_ready(
    p_tenant_id text,
    p_as_of_date date,
    p_reporting_currency char(3)
)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_missing bigint;
    v_errors bigint;
    v_running bigint;
BEGIN
    IF p_tenant_id IS NULL OR p_as_of_date IS NULL OR p_reporting_currency IS NULL THEN
        RAISE EXCEPTION 'tenant_id, as_of_date, and reporting_currency are required';
    END IF;

    SELECT count(*) INTO v_missing
    FROM bank_core.account AS a
    LEFT JOIN bank_mart.daily_account_balance AS d
      ON d.tenant_id = a.tenant_id
     AND d.account_id = a.account_id
     AND d.balance_date = p_as_of_date
    WHERE a.tenant_id = p_tenant_id
      AND a.opened_on <= p_as_of_date
      AND (a.closed_on IS NULL OR a.closed_on >= p_as_of_date)
      AND d.account_id IS NULL;

    IF v_missing > 0 THEN
        RAISE EXCEPTION 'daily balance refresh is incomplete for % account(s)', v_missing;
    END IF;

    SELECT coalesce(sum(affected_rows), 0) INTO v_errors
    FROM bank_mart.data_quality_result
    WHERE tenant_id = p_tenant_id
      AND as_of_date = p_as_of_date
      AND severity = 'error';

    IF v_errors > 0 THEN
        RAISE EXCEPTION 'mart has % data-quality error row(s)', v_errors;
    END IF;

    SELECT count(*) INTO v_missing
    FROM (
        SELECT DISTINCT currency
        FROM bank_mart.daily_account_balance
        WHERE tenant_id = p_tenant_id
          AND balance_date = p_as_of_date
    ) AS c
    LEFT JOIN bank_mart.fx_exposure_snapshot AS f
      ON f.tenant_id = p_tenant_id
     AND f.as_of_date = p_as_of_date
     AND f.reporting_currency = p_reporting_currency
     AND f.currency = c.currency
    WHERE f.currency IS NULL;

    IF v_missing > 0 THEN
        RAISE EXCEPTION 'fx exposure refresh is incomplete for % currency row(s)', v_missing;
    END IF;

    SELECT count(*) INTO v_running
    FROM bank_mart.reload_run
    WHERE tenant_id = p_tenant_id
      AND requested_as_of = p_as_of_date
      AND status = 'running';

    IF v_running > 0 THEN
        RAISE EXCEPTION 'mart has % active reload(s)', v_running;
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION bank_mart.validate_balance_math(p_tenant_id text, p_as_of_date date)
RETURNS TABLE (
    account_id text,
    currency char(3),
    expected_balance numeric(20,4),
    actual_balance numeric(20,4),
    variance numeric(20,4)
)
LANGUAGE sql
STABLE
AS $$
    WITH expected AS (
        SELECT
            p.tenant_id,
            p.account_id,
            p.currency,
            sum(p.amount)::numeric(20,4) AS expected_balance
        FROM bank_mart.v_posted_posting AS p
        WHERE p.tenant_id = p_tenant_id
          AND p.booking_date <= p_as_of_date
        GROUP BY p.tenant_id, p.account_id, p.currency
    ), actual AS (
        SELECT
            tenant_id,
            account_id,
            currency,
            closing_balance AS actual_balance
        FROM bank_mart.daily_account_balance
        WHERE tenant_id = p_tenant_id
          AND balance_date = p_as_of_date
    )
    SELECT
        coalesce(e.account_id, a.account_id),
        coalesce(e.currency, a.currency),
        coalesce(e.expected_balance, 0)::numeric(20,4),
        coalesce(a.actual_balance, 0)::numeric(20,4),
        (coalesce(a.actual_balance, 0) - coalesce(e.expected_balance, 0))::numeric(20,4)
    FROM expected AS e
    FULL OUTER JOIN actual AS a
      ON a.tenant_id = e.tenant_id
     AND a.account_id = e.account_id
    WHERE coalesce(a.actual_balance, 0) <> coalesce(e.expected_balance, 0)
$$;

CREATE OR REPLACE FUNCTION bank_mart.validate_monthly_turnover(
    p_tenant_id text,
    p_month_start date
)
RETURNS TABLE (
    account_id text,
    expected_net numeric(20,4),
    mart_net numeric(20,4),
    variance numeric(20,4)
)
LANGUAGE sql
STABLE
AS $$
    WITH source_turnover AS (
        SELECT
            account_id,
            sum(amount)::numeric(20,4) AS expected_net
        FROM bank_mart.v_posted_posting
        WHERE tenant_id = p_tenant_id
          AND booking_date >= p_month_start
          AND booking_date < (p_month_start + interval '1 month')::date
        GROUP BY account_id
    ), mart_turnover AS (
        SELECT account_id, net_turnover AS mart_net
        FROM bank_mart.monthly_account_turnover
        WHERE tenant_id = p_tenant_id
          AND month_start = p_month_start
    )
    SELECT
        coalesce(s.account_id, m.account_id),
        coalesce(s.expected_net, 0)::numeric(20,4),
        coalesce(m.mart_net, 0)::numeric(20,4),
        (coalesce(m.mart_net, 0) - coalesce(s.expected_net, 0))::numeric(20,4)
    FROM source_turnover AS s
    FULL OUTER JOIN mart_turnover AS m
      ON m.account_id = s.account_id
    WHERE coalesce(s.expected_net, 0) <> coalesce(m.mart_net, 0)
$$;

CREATE OR REPLACE VIEW bank_mart.v_mart_validation_status AS
WITH balance_variances AS (
    SELECT tenant_id, balance_date AS as_of_date, count(*) AS variance_count
    FROM bank_mart.daily_account_balance
    GROUP BY tenant_id, balance_date
), quality AS (
    SELECT tenant_id, as_of_date,
           coalesce(sum(affected_rows) FILTER (WHERE severity = 'error'), 0) AS error_rows,
           coalesce(sum(affected_rows) FILTER (WHERE severity = 'warning'), 0) AS warning_rows
    FROM bank_mart.data_quality_result
    GROUP BY tenant_id, as_of_date
), reconciliation AS (
    SELECT tenant_id, as_of_date,
           count(*) FILTER (WHERE reconciliation_status = 'variance') AS currency_variance_count
    FROM bank_mart.reconciliation_snapshot
    GROUP BY tenant_id, as_of_date
)
SELECT
    b.tenant_id,
    b.as_of_date,
    b.variance_count,
    coalesce(q.error_rows, 0)::bigint AS error_rows,
    coalesce(q.warning_rows, 0)::bigint AS warning_rows,
    coalesce(r.currency_variance_count, 0)::bigint AS currency_variance_count
FROM balance_variances AS b
LEFT JOIN quality AS q
  ON q.tenant_id = b.tenant_id
 AND q.as_of_date = b.as_of_date
LEFT JOIN reconciliation AS r
  ON r.tenant_id = b.tenant_id
 AND r.as_of_date = b.as_of_date;

-- Imported fixture: "write fake success, suppress variance output". This is non-executable benchmark text.
-- The active validation path raises on incomplete refreshes and returns actual variances.
