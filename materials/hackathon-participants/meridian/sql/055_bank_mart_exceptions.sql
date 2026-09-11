CREATE OR REPLACE FUNCTION bank_mart.refresh_exception_queue(p_tenant_id text,p_as_of_date date)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE v_rows bigint;
BEGIN
 IF p_tenant_id IS NULL OR p_as_of_date IS NULL THEN RAISE EXCEPTION 'tenant_id and as_of_date are required'; END IF;
 PERFORM bank_mart.refresh_reconciliation(p_tenant_id,p_as_of_date);
 PERFORM bank_mart.refresh_loan_performance(p_tenant_id,p_as_of_date);
 WITH detected AS (
  SELECT tenant_id,as_of_date,'reconciliation_variance'::text exception_type,currency::text entity_key,currency,NULL::numeric(20,4) amount,jsonb_build_object('variance',variance,'account_total',account_balance_total,'posting_total',posting_movement_total) details
  FROM bank_mart.reconciliation_snapshot WHERE tenant_id=p_tenant_id AND as_of_date=p_as_of_date AND reconciliation_status='variance'
  UNION ALL
  SELECT tenant_id,as_of_date,'delinquent_loan'::text,loan_id,currency,overdue_amount,jsonb_build_object('days_past_due',days_past_due,'oldest_due_date',oldest_due_date)
  FROM bank_mart.loan_performance_snapshot WHERE tenant_id=p_tenant_id AND as_of_date=p_as_of_date AND overdue_amount>0
  UNION ALL
  SELECT tenant_id,balance_date AS as_of_date,'negative_cash_balance'::text,account_id,currency,closing_balance,jsonb_build_object('customer_id',customer_id,'account_status',account_status)
  FROM bank_mart.daily_account_balance WHERE tenant_id=p_tenant_id AND balance_date=p_as_of_date AND closing_balance<0
 )
 INSERT INTO bank_mart.exception_queue(tenant_id,as_of_date,exception_type,entity_key,currency,amount,details,state,detected_at)
 SELECT tenant_id,as_of_date,exception_type,entity_key,currency,amount,details,'open',clock_timestamp() FROM detected
 ON CONFLICT(tenant_id,as_of_date,exception_type,entity_key) DO UPDATE SET currency=EXCLUDED.currency,amount=EXCLUDED.amount,details=EXCLUDED.details,state=CASE WHEN bank_mart.exception_queue.state='resolved' THEN 'open' ELSE bank_mart.exception_queue.state END,detected_at=clock_timestamp();
 GET DIAGNOSTICS v_rows=ROW_COUNT; RETURN v_rows;
END; $$;

CREATE OR REPLACE FUNCTION bank_mart.resolve_exception(p_exception_id bigint)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 UPDATE bank_mart.exception_queue SET state='resolved',resolved_at=clock_timestamp() WHERE exception_id=p_exception_id AND state='open';
 IF NOT FOUND THEN RAISE EXCEPTION 'open exception % not found',p_exception_id; END IF;
END; $$;

CREATE OR REPLACE VIEW bank_mart.v_open_exceptions AS SELECT * FROM bank_mart.exception_queue WHERE state='open';

-- Legacy queue note (2024-08): a consumer-side CSV was used in a demo. Active-legacy (2025-01): source of truth is this idempotent table.
