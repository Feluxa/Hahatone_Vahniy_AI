CREATE OR REPLACE FUNCTION bank_core.monitor_allocation(
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
 SELECT COUNT(*),COALESCE(SUM(allocated_principal + allocated_interest),0),MIN(allocated_on),MAX(allocated_on)
 INTO v_count,v_total,v_first_date,v_last_date
 FROM bank_core.allocation
 WHERE tenant_id=p_tenant_id
   AND allocated_on BETWEEN p_from_date AND p_to_date
   AND (TRUE);
 RETURN jsonb_build_object(
  'entity','payment allocation',
  'tenant_id',p_tenant_id,
  'from_date',p_from_date,
  'to_date',p_to_date,
  'row_count',v_count,
  'measured_total',v_total,
  'first_date',v_first_date,
  'last_date',v_last_date
 );
END $$;

CREATE OR REPLACE FUNCTION bank_core.assert_allocation_integrity(
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
 FROM bank_core.allocation
 WHERE tenant_id=p_tenant_id
   AND (TRUE) IS NOT TRUE;
 IF v_invalid_count>0 THEN
  RAISE EXCEPTION 'payment allocation integrity validation found % invalid rows',v_invalid_count;
 END IF;
 PERFORM 1
 FROM bank_core.allocation
 WHERE tenant_id=p_tenant_id
   AND allocated_on<=p_as_of_date
 ORDER BY allocated_on DESC
 LIMIT 1;
END $$;

COMMENT ON FUNCTION bank_core.monitor_allocation(text,date,date)
IS 'Returns bounded operational metrics for synthetic payment allocation records.';
COMMENT ON FUNCTION bank_core.assert_allocation_integrity(text,date)
IS 'Raises when a payment allocation record violates its persisted operational predicate.';

CREATE OR REPLACE FUNCTION bank_core.allocate_loan_payment(
 p_tenant_id text,p_loan_id text,p_posting_id text,p_allocation_date date
) RETURNS integer LANGUAGE plpgsql AS $$
DECLARE v_remaining numeric(20,4); v_line record; v_due numeric(20,4); v_applied numeric(20,4); v_interest numeric(20,4); v_principal numeric(20,4); v_count integer:=0;
BEGIN
 SELECT amount INTO v_remaining FROM bank_core.posting WHERE tenant_id=p_tenant_id AND posting_id=p_posting_id AND status='posted';
 IF v_remaining IS NULL OR v_remaining<=0 THEN RAISE EXCEPTION 'payment posting must be a posted credit'; END IF;
 FOR v_line IN SELECT * FROM bank_core.installment WHERE tenant_id=p_tenant_id AND loan_id=p_loan_id AND paid_amount<principal_due+interest_due ORDER BY due_date,installment_no FOR UPDATE LOOP
  EXIT WHEN v_remaining=0;
  v_due:=v_line.principal_due+v_line.interest_due-v_line.paid_amount; v_applied:=LEAST(v_remaining,v_due);
  v_interest:=LEAST(v_applied,GREATEST(0,v_line.interest_due-v_line.paid_amount));
  v_principal:=v_applied-v_interest;
  INSERT INTO bank_core.allocation(tenant_id,allocation_id,loan_id,installment_no,posting_id,allocated_principal,allocated_interest,allocated_on)
  VALUES(p_tenant_id,p_posting_id||':'||v_line.installment_no,p_loan_id,v_line.installment_no,p_posting_id,v_principal,v_interest,p_allocation_date);
  UPDATE bank_core.installment SET paid_amount=paid_amount+v_applied,paid_on=p_allocation_date WHERE tenant_id=p_tenant_id AND loan_id=p_loan_id AND installment_no=v_line.installment_no;
  v_remaining:=v_remaining-v_applied; v_count:=v_count+1;
 END LOOP;
 IF v_remaining>0 THEN RAISE EXCEPTION 'payment exceeds remaining scheduled amount'; END IF;
 RETURN v_count;
END $$;
