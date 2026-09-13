BEGIN;
INSERT INTO bank_core.tenant(tenant_id,legal_name,base_currency,operational_date) VALUES ('sql_loan','SQL Loan Tenant','RUB',DATE '2026-01-30');
INSERT INTO bank_core.customer(tenant_id,customer_id,display_name) VALUES ('sql_loan','customer','Synthetic Customer');
INSERT INTO bank_core.account(tenant_id,account_id,customer_id,currency,status,opened_on) VALUES ('sql_loan','loan-account','customer','RUB','open',DATE '2026-01-01');
INSERT INTO bank_core.loan(tenant_id,loan_id,customer_id,account_id,principal,annual_rate,opened_on,maturity_date,status) VALUES ('sql_loan','loan-1','customer','loan-account',120.0000,0.12000000,DATE '2026-01-01',DATE '2026-04-01','active');
SELECT bank_core.build_monthly_schedule('sql_loan','loan-1');
SELECT bank_core.post_ledger_entry('sql_loan','payment','loan-account',DATE '2026-02-01',DATE '2026-02-01',40.0000,'RUB','test','payment-key');
SELECT bank_core.allocate_loan_payment('sql_loan','loan-1','payment',DATE '2026-02-01');
SELECT bank_core.run_balance_audit('sql_loan',DATE '2026-02-01','audit-1');
DO $$ BEGIN IF (SELECT count(*) FROM bank_core.allocation WHERE tenant_id='sql_loan')=0 OR (SELECT count(*) FROM bank_core.balance_audit WHERE tenant_id='sql_loan')<>1 THEN RAISE EXCEPTION 'loan allocation failed'; END IF; END $$;
ROLLBACK;

