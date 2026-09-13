CREATE TABLE IF NOT EXISTS bank_core.fx_rate (
 rate_date date NOT NULL, from_currency char(3) NOT NULL, to_currency char(3) NOT NULL,
 rate numeric(20,8) NOT NULL, source_name text NOT NULL DEFAULT 'synthetic-reference',
 loaded_at timestamptz NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY(rate_date,from_currency,to_currency),
 CHECK (from_currency ~ '^[A-Z]{3}$'), CHECK (to_currency ~ '^[A-Z]{3}$'), CHECK (from_currency <> to_currency), CHECK (rate > 0)
);
CREATE TABLE IF NOT EXISTS bank_core.fx_conversion (
 tenant_id text NOT NULL, conversion_id text NOT NULL, rate_date date NOT NULL,
 debit_account_id text NOT NULL, credit_account_id text NOT NULL, sold_amount numeric(20,4) NOT NULL,
 bought_amount numeric(20,4) NOT NULL, sold_currency char(3) NOT NULL, bought_currency char(3) NOT NULL,
 applied_rate numeric(20,8) NOT NULL, status text NOT NULL DEFAULT 'received',
 idempotency_key text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY (tenant_id,conversion_id), CHECK (sold_amount > 0 AND bought_amount > 0 AND applied_rate > 0),
 CHECK (sold_currency <> bought_currency), CHECK (status IN ('received','posted','reversed'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_fx_conversion_idempotency ON bank_core.fx_conversion(tenant_id,idempotency_key);

