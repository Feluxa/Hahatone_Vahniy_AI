CREATE TABLE IF NOT EXISTS bank_mart.customer_position_snapshot (
    tenant_id text NOT NULL,
    as_of_date date NOT NULL,
    customer_id text NOT NULL,
    currency char(3) NOT NULL,
    account_count integer NOT NULL,
    active_account_count integer NOT NULL,
    cash_balance numeric(20,4) NOT NULL,
    loan_principal numeric(20,4) NOT NULL,
    overdue_amount numeric(20,4) NOT NULL,
    net_position numeric(20,4) NOT NULL,
    refreshed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, as_of_date, customer_id, currency)
);

CREATE OR REPLACE FUNCTION bank_mart.refresh_customer_positions(p_tenant_id text,p_as_of_date date)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE v_rows bigint;
BEGIN
 IF p_tenant_id IS NULL OR p_as_of_date IS NULL THEN RAISE EXCEPTION 'tenant_id and as_of_date are required'; END IF;
 PERFORM bank_mart.refresh_daily_balances(p_tenant_id,p_as_of_date);
 PERFORM bank_mart.refresh_loan_performance(p_tenant_id,p_as_of_date);
 DELETE FROM bank_mart.customer_position_snapshot WHERE tenant_id=p_tenant_id AND as_of_date=p_as_of_date;
 WITH cash AS (
   SELECT tenant_id,customer_id,currency,count(*)::integer account_count,count(*) FILTER(WHERE account_status='open')::integer active_account_count,sum(closing_balance)::numeric(20,4) cash_balance
   FROM bank_mart.daily_account_balance WHERE tenant_id=p_tenant_id AND balance_date=p_as_of_date GROUP BY tenant_id,customer_id,currency
 ), loans AS (
   SELECT tenant_id,customer_id,currency,sum(principal)::numeric(20,4) loan_principal,sum(overdue_amount)::numeric(20,4) overdue_amount
   FROM bank_mart.loan_performance_snapshot WHERE tenant_id=p_tenant_id AND as_of_date=p_as_of_date GROUP BY tenant_id,customer_id,currency
 ), keys AS (SELECT tenant_id,customer_id,currency FROM cash UNION SELECT tenant_id,customer_id,currency FROM loans)
 INSERT INTO bank_mart.customer_position_snapshot(tenant_id,as_of_date,customer_id,currency,account_count,active_account_count,cash_balance,loan_principal,overdue_amount,net_position,refreshed_at)
 SELECT k.tenant_id,p_as_of_date,k.customer_id,k.currency,coalesce(c.account_count,0),coalesce(c.active_account_count,0),coalesce(c.cash_balance,0),coalesce(l.loan_principal,0),coalesce(l.overdue_amount,0),(coalesce(c.cash_balance,0)-coalesce(l.loan_principal,0))::numeric(20,4),clock_timestamp()
 FROM keys k LEFT JOIN cash c USING(tenant_id,customer_id,currency) LEFT JOIN loans l USING(tenant_id,customer_id,currency);
 GET DIAGNOSTICS v_rows=ROW_COUNT; RETURN v_rows;
END; $$;

CREATE OR REPLACE VIEW bank_mart.v_customer_position_summary AS
SELECT tenant_id,as_of_date,currency,count(*)::integer customer_count,sum(cash_balance)::numeric(20,4) cash_total,sum(loan_principal)::numeric(20,4) loan_total,sum(overdue_amount)::numeric(20,4) overdue_total FROM bank_mart.customer_position_snapshot GROUP BY tenant_id,as_of_date,currency;
