CREATE TABLE IF NOT EXISTS bank_core.transfer (
 tenant_id text NOT NULL, transfer_id text NOT NULL, debit_account_id text NOT NULL, credit_account_id text NOT NULL,
 amount numeric(20,4) NOT NULL, currency char(3) NOT NULL, requested_on date NOT NULL, value_date date NOT NULL,
 status text NOT NULL DEFAULT 'received', idempotency_key text NOT NULL, source_system text NOT NULL,
 reference text NOT NULL DEFAULT '', reversal_of text NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 completed_at timestamptz NULL, PRIMARY KEY (tenant_id, transfer_id),
 FOREIGN KEY (tenant_id,debit_account_id) REFERENCES bank_core.account(tenant_id,account_id),
 FOREIGN KEY (tenant_id,credit_account_id) REFERENCES bank_core.account(tenant_id,account_id),
 CHECK (amount > 0), CHECK (debit_account_id <> credit_account_id), CHECK (currency ~ '^[A-Z]{3}$'),
 CHECK (status IN ('received','validated','posted','reversed','rejected'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_transfer_idempotency ON bank_core.transfer(tenant_id,idempotency_key);
CREATE TABLE IF NOT EXISTS bank_core.transfer_event (
 tenant_id text NOT NULL, transfer_id text NOT NULL, event_no integer NOT NULL,
 event_type text NOT NULL, event_at timestamptz NOT NULL DEFAULT clock_timestamp(), actor text NOT NULL,
 details jsonb NOT NULL DEFAULT '{}'::jsonb, PRIMARY KEY (tenant_id,transfer_id,event_no),
 FOREIGN KEY (tenant_id,transfer_id) REFERENCES bank_core.transfer(tenant_id,transfer_id),
 CHECK (event_type IN ('received','validated','posted','reversed','rejected'))
);

