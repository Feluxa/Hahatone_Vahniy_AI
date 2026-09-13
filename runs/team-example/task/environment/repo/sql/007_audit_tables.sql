CREATE TABLE IF NOT EXISTS bank_core.balance_audit (
 tenant_id text NOT NULL, audit_id bigint GENERATED ALWAYS AS IDENTITY, account_id text NOT NULL,
 as_of_date date NOT NULL, expected_balance numeric(20,4) NOT NULL, observed_balance numeric(20,4) NOT NULL,
 difference numeric(20,4) NOT NULL, checked_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 run_id text NULL, PRIMARY KEY (tenant_id,audit_id),
 CHECK (difference = observed_balance - expected_balance)
);
CREATE INDEX IF NOT EXISTS ix_balance_audit_date ON bank_core.balance_audit(tenant_id,as_of_date,account_id);
CREATE TABLE IF NOT EXISTS bank_core.allocation (
 tenant_id text NOT NULL, allocation_id text NOT NULL, loan_id text NOT NULL, installment_no integer NOT NULL,
 posting_id text NOT NULL, allocated_principal numeric(20,4) NOT NULL DEFAULT 0,
 allocated_interest numeric(20,4) NOT NULL DEFAULT 0, allocated_on date NOT NULL,
 PRIMARY KEY(tenant_id,allocation_id), FOREIGN KEY(tenant_id,loan_id,installment_no)
 REFERENCES bank_core.installment(tenant_id,loan_id,installment_no), FOREIGN KEY(tenant_id,posting_id) REFERENCES bank_core.posting(tenant_id,posting_id),
 CHECK (allocated_principal >= 0 AND allocated_interest >= 0), CHECK (allocated_principal + allocated_interest > 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_allocation_posting_installment ON bank_core.allocation(tenant_id,posting_id,loan_id,installment_no);

