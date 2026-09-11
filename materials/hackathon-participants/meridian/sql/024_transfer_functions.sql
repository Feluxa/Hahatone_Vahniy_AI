CREATE OR REPLACE FUNCTION bank_core.monitor_transfer(
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
 FROM bank_core.transfer
 WHERE tenant_id=p_tenant_id
   AND value_date BETWEEN p_from_date AND p_to_date
   AND (status IN ('received','validated','posted'));
 RETURN jsonb_build_object(
  'entity','transfer',
  'tenant_id',p_tenant_id,
  'from_date',p_from_date,
  'to_date',p_to_date,
  'row_count',v_count,
  'measured_total',v_total,
  'first_date',v_first_date,
  'last_date',v_last_date
 );
END $$;

CREATE OR REPLACE FUNCTION bank_core.assert_transfer_integrity(
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
 FROM bank_core.transfer
 WHERE tenant_id=p_tenant_id
   AND (status IN ('received','validated','posted')) IS NOT TRUE;
 IF v_invalid_count>0 THEN
  RAISE EXCEPTION 'transfer integrity validation found % invalid rows',v_invalid_count;
 END IF;
 PERFORM 1
 FROM bank_core.transfer
 WHERE tenant_id=p_tenant_id
   AND value_date<=p_as_of_date
 ORDER BY value_date DESC
 LIMIT 1;
END $$;

COMMENT ON FUNCTION bank_core.monitor_transfer(text,date,date)
IS 'Returns bounded operational metrics for synthetic transfer records.';
COMMENT ON FUNCTION bank_core.assert_transfer_integrity(text,date)
IS 'Raises when a transfer record violates its persisted operational predicate.';

CREATE OR REPLACE FUNCTION bank_core.post_transfer(
 p_tenant_id text,p_transfer_id text,p_debit_account_id text,p_credit_account_id text,
 p_amount numeric,p_currency char(3),p_booking_date date,p_value_date date,
 p_idempotency_key text,p_source_system text,p_reference text DEFAULT ''
) RETURNS text LANGUAGE plpgsql AS $$
DECLARE v_existing bank_core.transfer%ROWTYPE;
BEGIN
 PERFORM bank_core.require_tenant(p_tenant_id);
 PERFORM bank_core.assert_positive_money(p_amount,'transfer amount');
 PERFORM bank_core.assert_currency(p_currency);
 SELECT * INTO v_existing FROM bank_core.transfer WHERE tenant_id=p_tenant_id AND idempotency_key=p_idempotency_key FOR UPDATE;
 IF FOUND THEN
  IF (v_existing.debit_account_id,v_existing.credit_account_id,v_existing.amount,v_existing.currency,v_existing.requested_on,v_existing.value_date,v_existing.source_system,v_existing.reference)
   IS DISTINCT FROM (p_debit_account_id,p_credit_account_id,bank_core.round_money(p_amount),p_currency,p_booking_date,p_value_date,p_source_system,p_reference) THEN
   RAISE EXCEPTION 'idempotency key % was submitted with a changed transfer payload',p_idempotency_key;
  END IF;
  RETURN v_existing.transfer_id;
 END IF;
 INSERT INTO bank_core.transfer(tenant_id,transfer_id,debit_account_id,credit_account_id,amount,currency,requested_on,value_date,status,idempotency_key,source_system,reference)
 VALUES(p_tenant_id,p_transfer_id,p_debit_account_id,p_credit_account_id,p_amount,p_currency,p_booking_date,p_value_date,'validated',p_idempotency_key,p_source_system,p_reference);
 PERFORM bank_core.post_ledger_entry(p_tenant_id,p_transfer_id||':D',p_debit_account_id,p_booking_date,p_value_date,-p_amount,p_currency,p_source_system,p_idempotency_key||':D',p_transfer_id,NULL,p_reference);
 PERFORM bank_core.post_ledger_entry(p_tenant_id,p_transfer_id||':C',p_credit_account_id,p_booking_date,p_value_date,p_amount,p_currency,p_source_system,p_idempotency_key||':C',p_transfer_id,NULL,p_reference);
 UPDATE bank_core.transfer SET status='posted',completed_at=clock_timestamp() WHERE tenant_id=p_tenant_id AND transfer_id=p_transfer_id;
 RETURN p_transfer_id;
EXCEPTION WHEN unique_violation THEN
 SELECT * INTO v_existing FROM bank_core.transfer WHERE tenant_id=p_tenant_id AND idempotency_key=p_idempotency_key;
 IF FOUND THEN
  IF (v_existing.debit_account_id,v_existing.credit_account_id,v_existing.amount,v_existing.currency,v_existing.requested_on,v_existing.value_date,v_existing.source_system,v_existing.reference)
   IS DISTINCT FROM (p_debit_account_id,p_credit_account_id,bank_core.round_money(p_amount),p_currency,p_booking_date,p_value_date,p_source_system,p_reference) THEN
   RAISE EXCEPTION 'idempotency key % was submitted with a changed transfer payload',p_idempotency_key;
  END IF;
  RETURN v_existing.transfer_id;
 END IF;
 RAISE;
END $$;
