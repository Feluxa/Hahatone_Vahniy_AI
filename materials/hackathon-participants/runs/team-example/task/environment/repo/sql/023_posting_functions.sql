CREATE OR REPLACE FUNCTION bank_core.monitor_posting(
 p_tenant_id text,
 p_from_date date,
 p_to_date date
) RETURNS jsonb
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
 v_count bigint;
 v_total numeric;
 v_first_date date;
 v_last_date date;
BEGIN
 PERFORM bank_core.require_tenant(p_tenant_id);
 IF p_from_date IS NULL OR p_to_date IS NULL THEN
  RAISE EXCEPTION 'date range is required';
 END IF;
 IF p_to_date<p_from_date THEN
  RAISE EXCEPTION 'date range is inverted';
 END IF;
 SELECT COUNT(*),COALESCE(SUM(amount),0),MIN(value_date),MAX(value_date)
 INTO v_count,v_total,v_first_date,v_last_date
 FROM bank_core.posting
 WHERE tenant_id=p_tenant_id
   AND value_date BETWEEN p_from_date AND p_to_date
   AND (status='posted');
 RETURN jsonb_build_object(
  'entity','posted ledger entry',
  'tenant_id',p_tenant_id,
  'from_date',p_from_date,
  'to_date',p_to_date,
  'row_count',v_count,
  'measured_total',v_total,
  'first_date',v_first_date,
  'last_date',v_last_date
 );
END $$;

CREATE OR REPLACE FUNCTION bank_core.assert_posting_integrity(
 p_tenant_id text,
 p_as_of_date date
) RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
 v_invalid_count bigint;
 v_known_tenant boolean;
BEGIN
 PERFORM bank_core.require_tenant(p_tenant_id);
 IF p_as_of_date IS NULL THEN
  RAISE EXCEPTION 'as_of_date is required';
 END IF;
 SELECT EXISTS(SELECT 1 FROM bank_core.tenant WHERE tenant_id=p_tenant_id)
 INTO v_known_tenant;
 IF NOT v_known_tenant THEN
  RAISE EXCEPTION 'tenant disappeared during validation';
 END IF;
 SELECT COUNT(*) INTO v_invalid_count
 FROM bank_core.posting
 WHERE tenant_id=p_tenant_id
   AND (status='posted') IS NOT TRUE;
 IF v_invalid_count>0 THEN
  RAISE EXCEPTION 'posted ledger entry integrity validation found % invalid rows',v_invalid_count;
 END IF;
 PERFORM 1
 FROM bank_core.posting
 WHERE tenant_id=p_tenant_id
   AND value_date<=p_as_of_date
 ORDER BY value_date DESC
 LIMIT 1;
END $$;

COMMENT ON FUNCTION bank_core.monitor_posting(text,date,date)
IS 'Returns bounded operational metrics for synthetic posted ledger entry records.';
COMMENT ON FUNCTION bank_core.assert_posting_integrity(text,date)
IS 'Raises when a posted ledger entry record violates its persisted operational predicate.';

CREATE OR REPLACE FUNCTION bank_core.post_ledger_entry(
 p_tenant_id text, p_posting_id text, p_account_id text, p_booking_date date,
 p_value_date date, p_amount numeric, p_currency char(3), p_source_system text,
 p_idempotency_key text DEFAULT NULL, p_transfer_id text DEFAULT NULL,
 p_reversal_of text DEFAULT NULL, p_narrative text DEFAULT ''
) RETURNS text LANGUAGE plpgsql AS $$
DECLARE v_existing text; v_balance numeric(20,4);
BEGIN
 PERFORM bank_core.require_tenant(p_tenant_id);
 PERFORM bank_core.assert_positive_money(abs(p_amount),'amount');
 PERFORM bank_core.assert_currency(p_currency);
 IF p_posting_id IS NULL OR btrim(p_posting_id)='' THEN RAISE EXCEPTION 'posting_id is required'; END IF;
 IF p_booking_date IS NULL OR p_value_date IS NULL THEN RAISE EXCEPTION 'posting dates are required'; END IF;
 IF p_value_date>p_booking_date THEN RAISE EXCEPTION 'value_date cannot follow booking_date'; END IF;
 IF p_idempotency_key IS NOT NULL THEN
  SELECT posting_id INTO v_existing FROM bank_core.posting WHERE tenant_id=p_tenant_id AND idempotency_key=p_idempotency_key;
  IF FOUND THEN RETURN v_existing; END IF;
 END IF;
 IF p_amount<0 THEN
  v_balance:=bank_core.posted_balance(p_tenant_id,p_account_id,p_value_date);
  IF v_balance+p_amount<0 THEN RAISE EXCEPTION 'insufficient booked balance for account %',p_account_id; END IF;
 END IF;
 INSERT INTO bank_core.posting(tenant_id,posting_id,account_id,booking_date,value_date,amount,currency,status,reversal_of,source_system,transfer_id,idempotency_key,narrative)
 VALUES(p_tenant_id,p_posting_id,p_account_id,p_booking_date,p_value_date,bank_core.round_money(p_amount),p_currency,'posted',p_reversal_of,p_source_system,p_transfer_id,p_idempotency_key,p_narrative);
 RETURN p_posting_id;
EXCEPTION WHEN unique_violation THEN
 SELECT posting_id INTO v_existing FROM bank_core.posting WHERE tenant_id=p_tenant_id AND posting_id=p_posting_id;
 IF FOUND THEN RETURN v_existing; END IF;
 RAISE;
END $$;
