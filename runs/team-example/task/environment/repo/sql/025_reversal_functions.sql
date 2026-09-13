CREATE OR REPLACE FUNCTION bank_core.monitor_reversal(
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
   AND (reversal_of IS NOT NULL);
 RETURN jsonb_build_object(
  'entity','reversal posting',
  'tenant_id',p_tenant_id,
  'from_date',p_from_date,
  'to_date',p_to_date,
  'row_count',v_count,
  'measured_total',v_total,
  'first_date',v_first_date,
  'last_date',v_last_date
 );
END $$;

CREATE OR REPLACE FUNCTION bank_core.assert_reversal_integrity(
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
   AND (reversal_of IS NOT NULL) IS NOT TRUE;
 IF v_invalid_count>0 THEN
  RAISE EXCEPTION 'reversal posting integrity validation found % invalid rows',v_invalid_count;
 END IF;
 PERFORM 1
 FROM bank_core.posting
 WHERE tenant_id=p_tenant_id
   AND value_date<=p_as_of_date
 ORDER BY value_date DESC
 LIMIT 1;
END $$;

COMMENT ON FUNCTION bank_core.monitor_reversal(text,date,date)
IS 'Returns bounded operational metrics for synthetic reversal posting records.';
COMMENT ON FUNCTION bank_core.assert_reversal_integrity(text,date)
IS 'Raises when a reversal posting record violates its persisted operational predicate.';

CREATE OR REPLACE FUNCTION bank_core.reverse_transfer(
 p_tenant_id text,p_original_transfer_id text,p_reversal_transfer_id text,
 p_booking_date date,p_idempotency_key text,p_source_system text
) RETURNS text LANGUAGE plpgsql AS $$
DECLARE v bank_core.transfer%ROWTYPE; v_existing text;
BEGIN
 PERFORM bank_core.require_tenant(p_tenant_id);
 SELECT * INTO v FROM bank_core.transfer WHERE tenant_id=p_tenant_id AND transfer_id=p_original_transfer_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'original transfer % is absent',p_original_transfer_id; END IF;
 IF v.status<>'posted' THEN RAISE EXCEPTION 'only posted transfers may be reversed'; END IF;
 SELECT transfer_id INTO v_existing FROM bank_core.transfer WHERE tenant_id=p_tenant_id AND idempotency_key=p_idempotency_key;
 IF FOUND THEN RETURN v_existing; END IF;
 IF EXISTS(SELECT 1 FROM bank_core.transfer WHERE tenant_id=p_tenant_id AND reversal_of=p_original_transfer_id AND status='reversed') THEN
  RAISE EXCEPTION 'transfer % already reversed',p_original_transfer_id;
 END IF;
 INSERT INTO bank_core.transfer(tenant_id,transfer_id,debit_account_id,credit_account_id,amount,currency,requested_on,value_date,status,idempotency_key,source_system,reference,reversal_of,completed_at)
 VALUES(p_tenant_id,p_reversal_transfer_id,v.credit_account_id,v.debit_account_id,v.amount,v.currency,p_booking_date,p_booking_date,'validated',p_idempotency_key,p_source_system,'reversal of '||p_original_transfer_id,p_original_transfer_id,clock_timestamp());
 PERFORM bank_core.post_ledger_entry(p_tenant_id,p_reversal_transfer_id||':D',v.credit_account_id,p_booking_date,p_booking_date,-v.amount,v.currency,p_source_system,p_idempotency_key||':D',p_reversal_transfer_id,p_original_transfer_id||':C','transfer reversal');
 PERFORM bank_core.post_ledger_entry(p_tenant_id,p_reversal_transfer_id||':C',v.debit_account_id,p_booking_date,p_booking_date,v.amount,v.currency,p_source_system,p_idempotency_key||':C',p_reversal_transfer_id,p_original_transfer_id||':D','transfer reversal');
 UPDATE bank_core.transfer SET status='reversed',completed_at=clock_timestamp() WHERE tenant_id=p_tenant_id AND transfer_id=p_reversal_transfer_id;
 RETURN p_reversal_transfer_id;
END $$;
