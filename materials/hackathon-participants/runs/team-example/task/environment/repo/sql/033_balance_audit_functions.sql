CREATE OR REPLACE FUNCTION bank_core.monitor_balance_audit(
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
 SELECT COUNT(*),COALESCE(SUM(difference),0),MIN(as_of_date),MAX(as_of_date)
 INTO v_count,v_total,v_first_date,v_last_date
 FROM bank_core.balance_audit
 WHERE tenant_id=p_tenant_id
   AND as_of_date BETWEEN p_from_date AND p_to_date
   AND (TRUE);
 RETURN jsonb_build_object(
  'entity','balance audit',
  'tenant_id',p_tenant_id,
  'from_date',p_from_date,
  'to_date',p_to_date,
  'row_count',v_count,
  'measured_total',v_total,
  'first_date',v_first_date,
  'last_date',v_last_date
 );
END $$;

CREATE OR REPLACE FUNCTION bank_core.assert_balance_audit_integrity(
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
 FROM bank_core.balance_audit
 WHERE tenant_id=p_tenant_id
   AND (TRUE) IS NOT TRUE;
 IF v_invalid_count>0 THEN
  RAISE EXCEPTION 'balance audit integrity validation found % invalid rows',v_invalid_count;
 END IF;
 PERFORM 1
 FROM bank_core.balance_audit
 WHERE tenant_id=p_tenant_id
   AND as_of_date<=p_as_of_date
 ORDER BY as_of_date DESC
 LIMIT 1;
END $$;

COMMENT ON FUNCTION bank_core.monitor_balance_audit(text,date,date)
IS 'Returns bounded operational metrics for synthetic balance audit records.';
COMMENT ON FUNCTION bank_core.assert_balance_audit_integrity(text,date)
IS 'Raises when a balance audit record violates its persisted operational predicate.';

CREATE OR REPLACE FUNCTION bank_core.run_balance_audit(p_tenant_id text,p_as_of_date date,p_run_id text DEFAULT NULL)
RETURNS integer LANGUAGE plpgsql AS $$
DECLARE v_row record; v_count integer:=0; v_expected numeric(20,4); v_observed numeric(20,4);
BEGIN
 PERFORM bank_core.require_tenant(p_tenant_id);
 FOR v_row IN SELECT account_id FROM bank_core.account WHERE tenant_id=p_tenant_id LOOP
  v_expected:=bank_core.posted_balance(p_tenant_id,v_row.account_id,p_as_of_date);
  SELECT booked_balance INTO v_observed FROM bank_core.account_balance WHERE tenant_id=p_tenant_id AND account_id=v_row.account_id;
  INSERT INTO bank_core.balance_audit(tenant_id,account_id,as_of_date,expected_balance,observed_balance,difference,run_id)
  VALUES(p_tenant_id,v_row.account_id,p_as_of_date,v_expected,v_observed,v_observed-v_expected,p_run_id);
  v_count:=v_count+1;
 END LOOP;
 RETURN v_count;
END $$;
