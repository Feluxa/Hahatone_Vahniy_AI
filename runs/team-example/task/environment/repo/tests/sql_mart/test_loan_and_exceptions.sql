BEGIN;

CREATE SCHEMA IF NOT EXISTS bank_core;
CREATE TABLE IF NOT EXISTS bank_core.account (
    tenant_id text, account_id text, customer_id text, currency char(3), status text,
    opened_on date, closed_on date, PRIMARY KEY (tenant_id, account_id)
);
CREATE TABLE IF NOT EXISTS bank_core.posting (
    tenant_id text, posting_id text, account_id text, booking_date date, value_date date,
    amount numeric(20,4), currency char(3), status text, reversal_of text, source_system text,
    PRIMARY KEY (tenant_id, posting_id)
);
CREATE TABLE IF NOT EXISTS bank_core.loan (tenant_id text, loan_id text, customer_id text, account_id text, principal numeric(20,4), annual_rate numeric(12,8), opened_on date, maturity_date date, status text, PRIMARY KEY(tenant_id,loan_id));
CREATE TABLE IF NOT EXISTS bank_core.installment (tenant_id text, loan_id text, installment_no integer, due_date date, principal_due numeric(20,4), interest_due numeric(20,4), paid_amount numeric(20,4), PRIMARY KEY(tenant_id,loan_id,installment_no));
CREATE TABLE IF NOT EXISTS bank_core.fx_rate (rate_date date, from_currency char(3), to_currency char(3), rate numeric(20,8), PRIMARY KEY(rate_date,from_currency,to_currency));

INSERT INTO bank_core.tenant(tenant_id, legal_name, base_currency, timezone_name, operational_date)
VALUES ('loan_test', 'Synthetic loan test tenant', 'USD', 'UTC', date '2026-03-01');
INSERT INTO bank_core.customer(tenant_id, customer_id, display_name)
VALUES ('loan_test', 'LC-1', 'Synthetic Loan Customer');
INSERT INTO bank_core.source_system(source_system, display_name)
VALUES ('synthetic', 'Synthetic SQL mart test source') ON CONFLICT (source_system) DO NOTHING;
INSERT INTO bank_core.account VALUES ('loan_test','L-USD','LC-1','USD','open',date '2026-02-01',NULL);
INSERT INTO bank_core.posting VALUES ('loan_test','LP-1','L-USD',date '2026-02-01',date '2026-02-01',200.0000,'USD','posted',NULL,'synthetic');
INSERT INTO bank_core.loan VALUES ('loan_test','LN-1','LC-1','L-USD',1000.0000,0.12000000,date '2026-01-01',date '2027-01-01','active');
INSERT INTO bank_core.installment VALUES ('loan_test','LN-1',1,date '2026-02-10',100.0000,10.0000,20.0000);

SELECT bank_mart.refresh_daily_balances('loan_test',date '2026-03-01');
SELECT bank_mart.refresh_loan_performance('loan_test',date '2026-03-01');
SELECT bank_mart.refresh_customer_positions('loan_test',date '2026-03-01');
SELECT bank_mart.refresh_exception_queue('loan_test',date '2026-03-01');

DO $$
DECLARE v_overdue numeric(20,4); v_position numeric(20,4); v_exceptions integer;
BEGIN
 SELECT overdue_amount INTO v_overdue FROM bank_mart.loan_performance_snapshot WHERE tenant_id='loan_test' AND as_of_date=date '2026-03-01' AND loan_id='LN-1';
 IF v_overdue <> 90.0000 THEN RAISE EXCEPTION 'expected overdue amount 90, got %',v_overdue; END IF;
 SELECT net_position INTO v_position FROM bank_mart.customer_position_snapshot WHERE tenant_id='loan_test' AND as_of_date=date '2026-03-01' AND customer_id='LC-1' AND currency='USD';
 IF v_position <> -800.0000 THEN RAISE EXCEPTION 'expected net position -800, got %',v_position; END IF;
 SELECT count(*) INTO v_exceptions FROM bank_mart.exception_queue WHERE tenant_id='loan_test' AND as_of_date=date '2026-03-01' AND exception_type='delinquent_loan' AND state='open';
 IF v_exceptions <> 1 THEN RAISE EXCEPTION 'expected one delinquency exception'; END IF;
END $$;

ROLLBACK;
