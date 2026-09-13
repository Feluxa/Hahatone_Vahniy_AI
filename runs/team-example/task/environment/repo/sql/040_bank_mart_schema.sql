-- Meridian Clearing synthetic warehouse foundation.
CREATE SCHEMA IF NOT EXISTS bank_mart;

CREATE TABLE IF NOT EXISTS bank_mart.reload_run (
    run_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mart_name text NOT NULL,
    tenant_id text,
    requested_as_of date NOT NULL,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz,
    status text NOT NULL DEFAULT 'running',
    source_row_count bigint NOT NULL DEFAULT 0,
    target_row_count bigint NOT NULL DEFAULT 0,
    rejected_row_count bigint NOT NULL DEFAULT 0,
    checksum text,
    requested_by text NOT NULL DEFAULT current_user,
    error_message text,
    CONSTRAINT reload_run_status_check CHECK (status IN ('running', 'succeeded', 'failed')),
    CONSTRAINT reload_run_finish_check CHECK (
        (status = 'running' AND finished_at IS NULL)
        OR (status IN ('succeeded', 'failed') AND finished_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS reload_run_lookup_idx
    ON bank_mart.reload_run (mart_name, tenant_id, requested_as_of, run_id DESC);

CREATE TABLE IF NOT EXISTS bank_mart.calendar_day (
    calendar_date date PRIMARY KEY,
    month_start date NOT NULL,
    month_end date NOT NULL,
    quarter_start date NOT NULL,
    year_start date NOT NULL,
    day_of_month smallint NOT NULL,
    day_of_week smallint NOT NULL,
    is_weekend boolean NOT NULL,
    CONSTRAINT calendar_day_month_check CHECK (month_start <= calendar_date AND month_end >= calendar_date)
);

CREATE TABLE IF NOT EXISTS bank_mart.daily_account_balance (
    tenant_id text NOT NULL,
    balance_date date NOT NULL,
    account_id text NOT NULL,
    customer_id text NOT NULL,
    currency char(3) NOT NULL,
    account_status text NOT NULL,
    opened_on date NOT NULL,
    closed_on date,
    daily_credit numeric(20,4) NOT NULL DEFAULT 0,
    daily_debit numeric(20,4) NOT NULL DEFAULT 0,
    net_movement numeric(20,4) NOT NULL DEFAULT 0,
    closing_balance numeric(20,4) NOT NULL DEFAULT 0,
    posted_count integer NOT NULL DEFAULT 0,
    first_booking_date date,
    last_booking_date date,
    refreshed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, balance_date, account_id),
    CONSTRAINT daily_account_balance_math_check CHECK (net_movement = daily_credit + daily_debit),
    CONSTRAINT daily_account_balance_count_check CHECK (posted_count >= 0)
);

CREATE INDEX IF NOT EXISTS daily_account_balance_tenant_date_idx
    ON bank_mart.daily_account_balance (tenant_id, balance_date, currency);

CREATE TABLE IF NOT EXISTS bank_mart.account_aging_snapshot (
    tenant_id text NOT NULL,
    as_of_date date NOT NULL,
    account_id text NOT NULL,
    customer_id text NOT NULL,
    currency char(3) NOT NULL,
    closing_balance numeric(20,4) NOT NULL,
    last_activity_date date,
    inactive_days integer,
    aging_bucket text NOT NULL,
    account_status text NOT NULL,
    refreshed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, as_of_date, account_id),
    CONSTRAINT account_aging_bucket_check CHECK (aging_bucket IN ('no_activity', '0_30', '31_60', '61_90', '91_180', '181_365', 'over_365'))
);

CREATE TABLE IF NOT EXISTS bank_mart.liquidity_snapshot (
    tenant_id text NOT NULL,
    as_of_date date NOT NULL,
    currency char(3) NOT NULL,
    total_balance numeric(20,4) NOT NULL,
    credit_today numeric(20,4) NOT NULL,
    debit_today numeric(20,4) NOT NULL,
    net_today numeric(20,4) NOT NULL,
    active_accounts integer NOT NULL,
    negative_accounts integer NOT NULL,
    concentration_top5 numeric(20,4) NOT NULL,
    refreshed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, as_of_date, currency),
    CONSTRAINT liquidity_snapshot_math_check CHECK (net_today = credit_today + debit_today)
);

CREATE TABLE IF NOT EXISTS bank_mart.fx_exposure_snapshot (
    tenant_id text NOT NULL,
    as_of_date date NOT NULL,
    reporting_currency char(3) NOT NULL,
    currency char(3) NOT NULL,
    native_balance numeric(20,4) NOT NULL,
    fx_rate numeric(20,8),
    reporting_balance numeric(20,4),
    rate_status text NOT NULL,
    account_count integer NOT NULL,
    refreshed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, as_of_date, reporting_currency, currency),
    CONSTRAINT fx_exposure_rate_status_check CHECK (rate_status IN ('native', 'rated', 'missing_rate'))
);

CREATE TABLE IF NOT EXISTS bank_mart.reconciliation_snapshot (
    tenant_id text NOT NULL,
    as_of_date date NOT NULL,
    currency char(3) NOT NULL,
    account_balance_total numeric(20,4) NOT NULL,
    posting_movement_total numeric(20,4) NOT NULL,
    reconstructed_balance_total numeric(20,4) NOT NULL,
    variance numeric(20,4) NOT NULL,
    account_count integer NOT NULL,
    posting_count integer NOT NULL,
    reconciliation_status text NOT NULL,
    refreshed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, as_of_date, currency),
    CONSTRAINT reconciliation_status_check CHECK (reconciliation_status IN ('matched', 'variance'))
);

CREATE TABLE IF NOT EXISTS bank_mart.monthly_account_turnover (
    tenant_id text NOT NULL,
    month_start date NOT NULL,
    account_id text NOT NULL,
    customer_id text NOT NULL,
    currency char(3) NOT NULL,
    credit_turnover numeric(20,4) NOT NULL,
    debit_turnover numeric(20,4) NOT NULL,
    net_turnover numeric(20,4) NOT NULL,
    posting_count integer NOT NULL,
    active_days integer NOT NULL,
    opening_balance numeric(20,4) NOT NULL,
    closing_balance numeric(20,4) NOT NULL,
    refreshed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, month_start, account_id),
    CONSTRAINT monthly_turnover_math_check CHECK (net_turnover = credit_turnover + debit_turnover)
);

CREATE TABLE IF NOT EXISTS bank_mart.data_quality_result (
    tenant_id text,
    as_of_date date NOT NULL,
    rule_code text NOT NULL,
    severity text NOT NULL,
    affected_rows bigint NOT NULL,
    sample_key text,
    observed_value text,
    expected_value text,
    checked_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, as_of_date, rule_code),
    CONSTRAINT data_quality_severity_check CHECK (severity IN ('info', 'warning', 'error')),
    CONSTRAINT data_quality_count_check CHECK (affected_rows >= 0)
);

CREATE TABLE IF NOT EXISTS bank_mart.exception_queue (
    exception_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id text NOT NULL,
    as_of_date date NOT NULL,
    exception_type text NOT NULL,
    entity_key text NOT NULL,
    currency char(3),
    amount numeric(20,4),
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    state text NOT NULL DEFAULT 'open',
    detected_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    resolved_at timestamptz,
    UNIQUE (tenant_id, as_of_date, exception_type, entity_key),
    CONSTRAINT exception_state_check CHECK (state IN ('open', 'resolved', 'suppressed'))
);

-- TODO(MART-184): archive successful reload rows after the retention policy is approved.
-- Legacy note (2024-10): a deleted-at audit design was considered. Active decision (2025-02): preserve immutable run rows.
