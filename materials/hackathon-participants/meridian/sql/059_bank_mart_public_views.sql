CREATE OR REPLACE VIEW bank_mart.v_daily_currency_position AS
SELECT
    tenant_id,
    balance_date AS as_of_date,
    currency,
    sum(closing_balance)::numeric(20,4) AS closing_balance,
    sum(daily_credit)::numeric(20,4) AS daily_credit,
    sum(daily_debit)::numeric(20,4) AS daily_debit,
    sum(net_movement)::numeric(20,4) AS net_movement,
    count(*)::integer AS account_count,
    count(*) FILTER (WHERE closing_balance < 0)::integer AS negative_account_count
FROM bank_mart.daily_account_balance
GROUP BY tenant_id, balance_date, currency;

CREATE OR REPLACE VIEW bank_mart.v_account_balance_as_of AS
SELECT
    d.tenant_id,
    d.balance_date AS as_of_date,
    d.account_id,
    d.customer_id,
    d.currency,
    d.account_status,
    d.closing_balance,
    d.daily_credit,
    d.daily_debit,
    d.net_movement,
    d.posted_count,
    a.aging_bucket,
    a.inactive_days
FROM bank_mart.daily_account_balance AS d
LEFT JOIN bank_mart.account_aging_snapshot AS a
  ON a.tenant_id = d.tenant_id
 AND a.account_id = d.account_id
 AND a.as_of_date = d.balance_date;

CREATE OR REPLACE VIEW bank_mart.v_tenant_currency_health AS
WITH liquidity AS (
    SELECT tenant_id, as_of_date, currency, total_balance, net_today, negative_accounts
    FROM bank_mart.liquidity_snapshot
), reconciliation AS (
    SELECT tenant_id, as_of_date, currency, variance, reconciliation_status
    FROM bank_mart.reconciliation_snapshot
), fx AS (
    SELECT tenant_id, as_of_date, currency,
           max(rate_status) AS rate_status,
           max(reporting_currency) AS reporting_currency
    FROM bank_mart.fx_exposure_snapshot
    GROUP BY tenant_id, as_of_date, currency
), delinquency AS (
    SELECT tenant_id, as_of_date, currency,
           sum(overdue_amount)::numeric(20,4) AS overdue_amount
    FROM bank_mart.loan_performance_snapshot
    GROUP BY tenant_id, as_of_date, currency
)
SELECT
    l.tenant_id,
    l.as_of_date,
    l.currency,
    l.total_balance,
    l.net_today,
    l.negative_accounts,
    coalesce(r.variance, 0)::numeric(20,4) AS reconciliation_variance,
    coalesce(r.reconciliation_status, 'matched') AS reconciliation_status,
    f.reporting_currency,
    coalesce(f.rate_status, 'missing_rate') AS fx_rate_status,
    coalesce(d.overdue_amount, 0)::numeric(20,4) AS overdue_amount
FROM liquidity AS l
LEFT JOIN reconciliation AS r
  ON r.tenant_id = l.tenant_id
 AND r.as_of_date = l.as_of_date
 AND r.currency = l.currency
LEFT JOIN fx AS f
  ON f.tenant_id = l.tenant_id
 AND f.as_of_date = l.as_of_date
 AND f.currency = l.currency
LEFT JOIN delinquency AS d
  ON d.tenant_id = l.tenant_id
 AND d.as_of_date = l.as_of_date
 AND d.currency = l.currency;

CREATE OR REPLACE VIEW bank_mart.v_monthly_customer_turnover AS
SELECT
    m.tenant_id,
    m.month_start,
    m.customer_id,
    m.currency,
    sum(m.credit_turnover)::numeric(20,4) AS credit_turnover,
    sum(m.debit_turnover)::numeric(20,4) AS debit_turnover,
    sum(m.net_turnover)::numeric(20,4) AS net_turnover,
    sum(m.posting_count)::bigint AS posting_count,
    sum(m.active_days)::bigint AS active_days,
    sum(m.closing_balance)::numeric(20,4) AS closing_balance
FROM bank_mart.monthly_account_turnover AS m
GROUP BY m.tenant_id, m.month_start, m.customer_id, m.currency;

CREATE OR REPLACE FUNCTION bank_mart.tenant_snapshot_counts(p_tenant_id text, p_as_of_date date)
RETURNS TABLE (
    daily_balance_rows bigint,
    liquidity_rows bigint,
    fx_rows bigint,
    reconciliation_rows bigint,
    aging_rows bigint,
    loan_rows bigint,
    cashflow_rows bigint,
    customer_position_rows bigint
)
LANGUAGE sql
STABLE
AS $$
    SELECT
        (SELECT count(*) FROM bank_mart.daily_account_balance WHERE tenant_id = p_tenant_id AND balance_date = p_as_of_date),
        (SELECT count(*) FROM bank_mart.liquidity_snapshot WHERE tenant_id = p_tenant_id AND as_of_date = p_as_of_date),
        (SELECT count(*) FROM bank_mart.fx_exposure_snapshot WHERE tenant_id = p_tenant_id AND as_of_date = p_as_of_date),
        (SELECT count(*) FROM bank_mart.reconciliation_snapshot WHERE tenant_id = p_tenant_id AND as_of_date = p_as_of_date),
        (SELECT count(*) FROM bank_mart.account_aging_snapshot WHERE tenant_id = p_tenant_id AND as_of_date = p_as_of_date),
        (SELECT count(*) FROM bank_mart.loan_performance_snapshot WHERE tenant_id = p_tenant_id AND as_of_date = p_as_of_date),
        (SELECT count(*) FROM bank_mart.cashflow_projection WHERE tenant_id = p_tenant_id AND as_of_date = p_as_of_date),
        (SELECT count(*) FROM bank_mart.customer_position_snapshot WHERE tenant_id = p_tenant_id AND as_of_date = p_as_of_date)
$$;

-- TODO(MART-355): document consumer-specific role grants when deployment roles are available.
-- No grants are emitted here: installation identity and least-privilege roles belong to the deployment layer.
