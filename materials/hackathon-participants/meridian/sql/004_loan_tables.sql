CREATE TABLE IF NOT EXISTS bank_core.loan (
 tenant_id text NOT NULL, loan_id text NOT NULL, customer_id text NOT NULL, account_id text NOT NULL,
 principal numeric(20,4) NOT NULL, annual_rate numeric(12,8) NOT NULL, opened_on date NOT NULL,
 maturity_date date NOT NULL, status text NOT NULL,
 payment_frequency text NOT NULL DEFAULT 'monthly', created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,loan_id), FOREIGN KEY (tenant_id,customer_id) REFERENCES bank_core.customer(tenant_id,customer_id),
 FOREIGN KEY (tenant_id,account_id) REFERENCES bank_core.account(tenant_id,account_id),
 CHECK (principal > 0), CHECK (annual_rate >= 0), CHECK (maturity_date > opened_on),
 CHECK (status IN ('active','delinquent','paid_off','written_off')), CHECK (payment_frequency IN ('monthly','quarterly'))
);
CREATE TABLE IF NOT EXISTS bank_core.installment (
 tenant_id text NOT NULL, loan_id text NOT NULL, installment_no integer NOT NULL, due_date date NOT NULL,
 principal_due numeric(20,4) NOT NULL, interest_due numeric(20,4) NOT NULL, paid_amount numeric(20,4) NOT NULL DEFAULT 0,
 paid_on date NULL, status text NOT NULL DEFAULT 'due', PRIMARY KEY(tenant_id,loan_id,installment_no),
 FOREIGN KEY (tenant_id,loan_id) REFERENCES bank_core.loan(tenant_id,loan_id),
 CHECK (installment_no > 0), CHECK (principal_due >= 0), CHECK (interest_due >= 0), CHECK (paid_amount >= 0),
 CHECK (status IN ('scheduled','due','part_paid','paid','overdue','waived'))
);
CREATE INDEX IF NOT EXISTS ix_installment_due ON bank_core.installment(tenant_id,due_date) WHERE status IN ('due','part_paid','overdue');

