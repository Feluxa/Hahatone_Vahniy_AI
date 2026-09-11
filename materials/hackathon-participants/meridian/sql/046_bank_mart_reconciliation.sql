CREATE OR REPLACE FUNCTION bank_mart.refresh_reconciliation(p_tenant_id text,p_as_of_date date)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE v_rows bigint;
BEGIN
 IF p_tenant_id IS NULL OR p_as_of_date IS NULL THEN RAISE EXCEPTION 'tenant_id and as_of_date are required'; END IF;
 PERFORM bank_mart.refresh_daily_balances(p_tenant_id,p_as_of_date);
 DELETE FROM bank_mart.reconciliation_snapshot WHERE tenant_id=p_tenant_id AND as_of_date=p_as_of_date;
 WITH account_totals AS (
   SELECT tenant_id,currency,sum(closing_balance)::numeric(20,4) AS account_balance_total,count(*)::integer AS account_count
   FROM bank_mart.daily_account_balance WHERE tenant_id=p_tenant_id AND balance_date=p_as_of_date GROUP BY tenant_id,currency
 ), posting_totals AS (
   SELECT p.tenant_id,p.currency,sum(p.amount)::numeric(20,4) AS posting_movement_total,count(*)::integer AS posting_count
   FROM bank_mart.v_posted_posting p WHERE p.tenant_id=p_tenant_id AND p.booking_date<=p_as_of_date GROUP BY p.tenant_id,p.currency
 ), currency_set AS (
   SELECT tenant_id,currency FROM account_totals UNION SELECT tenant_id,currency FROM posting_totals
 )
 INSERT INTO bank_mart.reconciliation_snapshot (
   tenant_id,as_of_date,currency,account_balance_total,posting_movement_total,reconstructed_balance_total,
   variance,account_count,posting_count,reconciliation_status,refreshed_at
 )
 SELECT s.tenant_id,p_as_of_date,s.currency,coalesce(a.account_balance_total,0),coalesce(p.posting_movement_total,0),
   coalesce(p.posting_movement_total,0),
   (coalesce(a.account_balance_total,0)-coalesce(p.posting_movement_total,0))::numeric(20,4),
   coalesce(a.account_count,0),coalesce(p.posting_count,0),
   CASE WHEN coalesce(a.account_balance_total,0)=coalesce(p.posting_movement_total,0) THEN 'matched' ELSE 'variance' END,clock_timestamp()
 FROM currency_set s LEFT JOIN account_totals a ON a.tenant_id=s.tenant_id AND a.currency=s.currency
 LEFT JOIN posting_totals p ON p.tenant_id=s.tenant_id AND p.currency=s.currency;
 GET DIAGNOSTICS v_rows=ROW_COUNT; RETURN v_rows;
END; $$;

CREATE OR REPLACE VIEW bank_mart.v_reconciliation_variance AS
SELECT * FROM bank_mart.reconciliation_snapshot WHERE reconciliation_status='variance';
