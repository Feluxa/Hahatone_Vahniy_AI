CREATE SCHEMA IF NOT EXISTS bank_core;
COMMENT ON SCHEMA bank_core IS 'Synthetic Meridian Clearing operational ledger.';
CREATE TABLE IF NOT EXISTS bank_core.tenant (
 tenant_id text PRIMARY KEY, legal_name text NOT NULL, base_currency char(3) NOT NULL,
 timezone_name text NOT NULL DEFAULT 'UTC', operational_date date NOT NULL,
 status text NOT NULL DEFAULT 'active', created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK (base_currency ~ '^[A-Z]{3}$'), CHECK (status IN ('active','suspended','closed'))
);
CREATE TABLE IF NOT EXISTS bank_core.customer (
 tenant_id text NOT NULL REFERENCES bank_core.tenant(tenant_id), customer_id text NOT NULL,
 display_name text NOT NULL, customer_type text NOT NULL DEFAULT 'individual',
 tax_residency char(2) NOT NULL DEFAULT 'RU', status text NOT NULL DEFAULT 'active',
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY (tenant_id, customer_id),
 CHECK (customer_type IN ('individual','business')), CHECK (status IN ('active','blocked','closed'))
);
CREATE TABLE IF NOT EXISTS bank_core.account (
 tenant_id text NOT NULL, account_id text NOT NULL, customer_id text NOT NULL, currency char(3) NOT NULL,
 status text NOT NULL, opened_on date NOT NULL, closed_on date NULL,
 account_kind text NOT NULL DEFAULT 'current', nickname text NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,account_id), FOREIGN KEY (tenant_id,customer_id) REFERENCES bank_core.customer(tenant_id,customer_id),
 CHECK (currency ~ '^[A-Z]{3}$'), CHECK (status IN ('open','blocked','closed')), CHECK (closed_on IS NULL OR closed_on >= opened_on)
);
COMMENT ON TABLE bank_core.account IS 'Contract table: customer account with a zero opening balance.';

