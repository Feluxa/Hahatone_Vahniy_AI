CREATE OR REPLACE FUNCTION bank_mart.refresh_monthly_turnover(p_tenant_id text,p_month_start date)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE v_month_end date; v_rows bigint;
BEGIN
 IF p_tenant_id IS NULL OR p_month_start IS NULL OR p_month_start<>date_trunc('month',p_month_start)::date THEN RAISE EXCEPTION 'tenant and first calendar day of month are required'; END IF;
 v_month_end:=(p_month_start+interval '1 month - 1 day')::date;
 PERFORM bank_mart.refresh_daily_balances(p_tenant_id,v_month_end);
 DELETE FROM bank_mart.monthly_account_turnover WHERE tenant_id=p_tenant_id AND month_start=p_month_start;
 WITH movements AS (
 SELECT a.tenant_id,a.account_id,a.customer_id,a.currency,
   coalesce(sum(p.amount) FILTER(WHERE p.amount>0),0)::numeric(20,4) credit_turnover,
   coalesce(sum(p.amount) FILTER(WHERE p.amount<0),0)::numeric(20,4) debit_turnover,
   count(p.posting_id)::integer posting_count,
   count(DISTINCT p.booking_date)::integer active_days
 FROM bank_core.account a LEFT JOIN bank_mart.v_posted_posting p ON p.tenant_id=a.tenant_id AND p.account_id=a.account_id AND p.booking_date BETWEEN p_month_start AND v_month_end
 WHERE a.tenant_id=p_tenant_id GROUP BY a.tenant_id,a.account_id,a.customer_id,a.currency
 ), balances AS (
 SELECT tenant_id,account_id,
  coalesce(max(closing_balance) FILTER(WHERE balance_date=p_month_start-1),0)::numeric(20,4) opening_balance,
  coalesce(max(closing_balance) FILTER(WHERE balance_date=v_month_end),0)::numeric(20,4) closing_balance
 FROM bank_mart.daily_account_balance WHERE tenant_id=p_tenant_id AND balance_date BETWEEN p_month_start-1 AND v_month_end GROUP BY tenant_id,account_id
 )
 INSERT INTO bank_mart.monthly_account_turnover(tenant_id,month_start,account_id,customer_id,currency,credit_turnover,debit_turnover,net_turnover,posting_count,active_days,opening_balance,closing_balance,refreshed_at)
 SELECT m.tenant_id,p_month_start,m.account_id,m.customer_id,m.currency,m.credit_turnover,m.debit_turnover,(m.credit_turnover+m.debit_turnover)::numeric(20,4),m.posting_count,m.active_days,b.opening_balance,b.closing_balance,clock_timestamp() FROM movements m JOIN balances b ON b.tenant_id=m.tenant_id AND b.account_id=m.account_id;
 GET DIAGNOSTICS v_rows=ROW_COUNT; RETURN v_rows;
END; $$;

CREATE OR REPLACE VIEW bank_mart.v_monthly_turnover_summary AS
SELECT tenant_id,month_start,currency,sum(credit_turnover)::numeric(20,4) credit_turnover,sum(debit_turnover)::numeric(20,4) debit_turnover,sum(net_turnover)::numeric(20,4) net_turnover,sum(posting_count)::bigint posting_count FROM bank_mart.monthly_account_turnover GROUP BY tenant_id,month_start,currency;
