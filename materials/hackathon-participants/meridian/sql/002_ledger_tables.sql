CREATE TABLE IF NOT EXISTS bank_core.posting (
 tenant_id text NOT NULL, posting_id text NOT NULL, account_id text NOT NULL, booking_date date NOT NULL,
 value_date date NOT NULL, amount numeric(20,4) NOT NULL, currency char(3) NOT NULL, status text NOT NULL,
 reversal_of text NULL, source_system text NOT NULL,
 transfer_id text NULL, idempotency_key text NULL, narrative text NOT NULL DEFAULT '',
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY(tenant_id,posting_id),
 FOREIGN KEY (tenant_id,account_id) REFERENCES bank_core.account(tenant_id,account_id),
 CHECK (currency ~ '^[A-Z]{3}$'), CHECK (amount <> 0), CHECK (status IN ('pending','posted','void')),
 CHECK (value_date <= booking_date + 3660)
);
CREATE TABLE IF NOT EXISTS bank_core.posting_status_history (
 tenant_id text NOT NULL, posting_id text NOT NULL, old_status text NULL, new_status text NOT NULL,
 changed_at timestamptz NOT NULL DEFAULT clock_timestamp(), changed_by text NOT NULL,
 reason text NOT NULL DEFAULT '', PRIMARY KEY (tenant_id, posting_id, changed_at)
);
CREATE INDEX IF NOT EXISTS ix_posting_account_value ON bank_core.posting(tenant_id, account_id, value_date, posting_id);
CREATE INDEX IF NOT EXISTS ix_posting_transfer ON bank_core.posting(tenant_id, transfer_id) WHERE transfer_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_posting_idempotency ON bank_core.posting(tenant_id, idempotency_key)
 WHERE idempotency_key IS NOT NULL;
COMMENT ON TABLE bank_core.posting IS 'Signed ledger: credits positive, debits negative; only posted contributes.';

