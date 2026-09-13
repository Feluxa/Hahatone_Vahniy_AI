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
VALUES ('mart_test', 'Synthetic mart test tenant', 'USD', 'UTC', date '2026-01-03');
INSERT INTO bank_core.customer(tenant_id, customer_id, display_name)
VALUES ('mart_test', 'C-1', 'Synthetic Customer One'), ('mart_test', 'C-2', 'Synthetic Customer Two');
INSERT INTO bank_core.source_system(source_system, display_name)
VALUES ('synthetic', 'Synthetic SQL mart test source') ON CONFLICT (source_system) DO NOTHING;
INSERT INTO bank_core.account VALUES
 ('mart_test','A-USD','C-1','USD','open',date '2026-01-01',NULL),
 ('mart_test','A-EUR','C-2','EUR','open',date '2026-01-02',NULL);
INSERT INTO bank_core.posting VALUES
 ('mart_test','P-1','A-USD',date '2026-01-01',date '2026-01-01',100.0000,'USD','posted',NULL,'synthetic'),
 ('mart_test','P-2','A-USD',date '2026-01-03',date '2026-01-03',-25.0000,'USD','posted',NULL,'synthetic'),
 ('mart_test','P-3','A-EUR',date '2026-01-02',date '2026-01-02',40.0000,'EUR','posted',NULL,'synthetic'),
 ('mart_test','P-4','A-EUR',date '2026-01-03',date '2026-01-03',999.0000,'EUR','pending',NULL,'synthetic');
INSERT INTO bank_core.fx_rate VALUES (date '2026-01-03','EUR','USD',1.20000000);

SELECT bank_mart.refresh_tenant_mart('mart_test', date '2026-01-03', 'USD');

DO $$
DECLARE v_balance numeric(20,4); v_count integer; v_fx numeric(20,4); v_runs integer;
BEGIN
 SELECT closing_balance INTO v_balance FROM bank_mart.daily_account_balance WHERE tenant_id='mart_test' AND account_id='A-USD' AND balance_date=date '2026-01-03';
 IF v_balance <> 75.0000 THEN RAISE EXCEPTION 'expected USD balance 75, got %',v_balance; END IF;
 SELECT posted_count INTO v_count FROM bank_mart.daily_account_balance WHERE tenant_id='mart_test' AND account_id='A-EUR' AND balance_date=date '2026-01-03';
 IF v_count <> 0 THEN RAISE EXCEPTION 'pending posting contributed to balance'; END IF;
 SELECT reporting_balance INTO v_fx FROM bank_mart.fx_exposure_snapshot WHERE tenant_id='mart_test' AND as_of_date=date '2026-01-03' AND reporting_currency='USD' AND currency='EUR';
 IF v_fx <> 48.0000 THEN RAISE EXCEPTION 'expected EUR reporting exposure 48, got %',v_fx; END IF;
 SELECT count(*) INTO v_runs FROM bank_mart.reload_run WHERE tenant_id='mart_test' AND requested_as_of=date '2026-01-03' AND status='succeeded';
 IF v_runs <> 1 THEN RAISE EXCEPTION 'expected one successful audit run'; END IF;
END $$;

ROLLBACK;
