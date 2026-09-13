CREATE TABLE IF NOT EXISTS bank_core.inbound_message (
 tenant_id text NOT NULL, message_id text NOT NULL, message_type text NOT NULL, source_system text NOT NULL,
 idempotency_key text NOT NULL, received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 payload jsonb NOT NULL, status text NOT NULL DEFAULT 'received', error_code text NULL,
 processed_at timestamptz NULL, PRIMARY KEY (tenant_id,message_id),
 CHECK (message_type IN ('transfer','reversal','fx_conversion','loan_payment')),
 CHECK (status IN ('received','processing','processed','rejected'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_inbound_message_idempotency ON bank_core.inbound_message(tenant_id,source_system,idempotency_key);
CREATE TABLE IF NOT EXISTS bank_core.processing_lock (
 tenant_id text NOT NULL, lock_name text NOT NULL, locked_by text NOT NULL,
 locked_at timestamptz NOT NULL DEFAULT clock_timestamp(), expires_at timestamptz NOT NULL,
 PRIMARY KEY (tenant_id,lock_name), CHECK (expires_at > locked_at)
);
CREATE TABLE IF NOT EXISTS bank_core.reconciliation_run (
 tenant_id text NOT NULL, run_id text NOT NULL, as_of_date date NOT NULL, status text NOT NULL DEFAULT 'started',
 started_at timestamptz NOT NULL DEFAULT clock_timestamp(), completed_at timestamptz NULL,
 discrepancy_count integer NOT NULL DEFAULT 0, PRIMARY KEY (tenant_id,run_id),
 CHECK (status IN ('started','completed','failed')), CHECK (discrepancy_count >= 0)
);

