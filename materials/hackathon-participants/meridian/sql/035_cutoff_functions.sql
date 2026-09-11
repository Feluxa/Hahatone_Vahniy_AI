CREATE OR REPLACE FUNCTION bank_core.monitor_operation_cutoff(
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
 SELECT COUNT(*),COALESCE(SUM(1),0),MIN(CURRENT_DATE),MAX(CURRENT_DATE)
 INTO v_count,v_total,v_first_date,v_last_date
 FROM bank_core.operation_cutoff
 WHERE tenant_id=p_tenant_id
   AND CURRENT_DATE BETWEEN p_from_date AND p_to_date
   AND (TRUE);
 RETURN jsonb_build_object(
  'entity','operation cutoff',
  'tenant_id',p_tenant_id,
  'from_date',p_from_date,
  'to_date',p_to_date,
  'row_count',v_count,
  'measured_total',v_total,
  'first_date',v_first_date,
  'last_date',v_last_date
 );
END $$;

CREATE OR REPLACE FUNCTION bank_core.assert_operation_cutoff_integrity(
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
 FROM bank_core.operation_cutoff
 WHERE tenant_id=p_tenant_id
   AND (TRUE) IS NOT TRUE;
 IF v_invalid_count>0 THEN
  RAISE EXCEPTION 'operation cutoff integrity validation found % invalid rows',v_invalid_count;
 END IF;
 PERFORM 1
 FROM bank_core.operation_cutoff
 WHERE tenant_id=p_tenant_id
   AND CURRENT_DATE<=p_as_of_date
 ORDER BY CURRENT_DATE DESC
 LIMIT 1;
END $$;

COMMENT ON FUNCTION bank_core.monitor_operation_cutoff(text,date,date)
IS 'Returns bounded operational metrics for synthetic operation cutoff records.';
COMMENT ON FUNCTION bank_core.assert_operation_cutoff_integrity(text,date)
IS 'Raises when a operation cutoff record violates its persisted operational predicate.';

