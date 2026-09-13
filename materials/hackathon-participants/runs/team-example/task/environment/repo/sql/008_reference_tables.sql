CREATE TABLE IF NOT EXISTS bank_core.calendar_day (
 calendar_date date PRIMARY KEY, is_business_day boolean NOT NULL, holiday_name text NULL,
 CHECK ((is_business_day AND holiday_name IS NULL) OR NOT is_business_day)
);
CREATE TABLE IF NOT EXISTS bank_core.source_system (
 source_system text PRIMARY KEY, display_name text NOT NULL, is_active boolean NOT NULL DEFAULT true,
 supports_reversals boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS bank_core.account_limit (
 tenant_id text NOT NULL, account_id text NOT NULL, daily_debit_limit numeric(20,4) NOT NULL,
 effective_from date NOT NULL, effective_to date NULL, PRIMARY KEY(tenant_id,account_id,effective_from),
 FOREIGN KEY(tenant_id,account_id) REFERENCES bank_core.account(tenant_id,account_id),
 CHECK (daily_debit_limit >= 0), CHECK (effective_to IS NULL OR effective_to >= effective_from)
);
CREATE TABLE IF NOT EXISTS bank_core.operation_cutoff (
 tenant_id text NOT NULL, operation_type text NOT NULL, cutoff_time time NOT NULL,
 timezone_name text NOT NULL DEFAULT 'UTC', PRIMARY KEY(tenant_id,operation_type),
 CHECK (operation_type IN ('transfer','fx_conversion','loan_payment'))
);

