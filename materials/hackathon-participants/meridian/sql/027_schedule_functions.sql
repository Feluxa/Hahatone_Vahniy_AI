CREATE OR REPLACE FUNCTION bank_core.monitor_schedule(
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
 SELECT COUNT(*),COALESCE(SUM(principal_due + interest_due),0),MIN(due_date),MAX(due_date)
 INTO v_count,v_total,v_first_date,v_last_date
 FROM bank_core.installment
 WHERE tenant_id=p_tenant_id
   AND due_date BETWEEN p_from_date AND p_to_date
   AND (status IN ('scheduled','due','part_paid','overdue'));
 RETURN jsonb_build_object(
  'entity','loan schedule line',
  'tenant_id',p_tenant_id,
  'from_date',p_from_date,
  'to_date',p_to_date,
  'row_count',v_count,
  'measured_total',v_total,
  'first_date',v_first_date,
  'last_date',v_last_date
 );
END $$;

CREATE OR REPLACE FUNCTION bank_core.assert_schedule_integrity(
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
 FROM bank_core.installment
 WHERE tenant_id=p_tenant_id
   AND (status IN ('scheduled','due','part_paid','overdue')) IS NOT TRUE;
 IF v_invalid_count>0 THEN
  RAISE EXCEPTION 'loan schedule line integrity validation found % invalid rows',v_invalid_count;
 END IF;
 PERFORM 1
 FROM bank_core.installment
 WHERE tenant_id=p_tenant_id
   AND due_date<=p_as_of_date
 ORDER BY due_date DESC
 LIMIT 1;
END $$;

COMMENT ON FUNCTION bank_core.monitor_schedule(text,date,date)
IS 'Returns bounded operational metrics for synthetic loan schedule line records.';
COMMENT ON FUNCTION bank_core.assert_schedule_integrity(text,date)
IS 'Raises when a loan schedule line record violates its persisted operational predicate.';

CREATE OR REPLACE FUNCTION bank_core.build_monthly_schedule(p_tenant_id text,p_loan_id text) RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE v_loan bank_core.loan%ROWTYPE; v_date date; v_no integer:=0; v_remaining numeric(20,4); v_principal_due numeric(20,4); v_interest_due numeric(20,4);
BEGIN
 PERFORM bank_core.require_tenant(p_tenant_id);
 SELECT * INTO v_loan FROM bank_core.loan WHERE tenant_id=p_tenant_id AND loan_id=p_loan_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'loan % is absent',p_loan_id; END IF;
 IF EXISTS(SELECT 1 FROM bank_core.installment WHERE tenant_id=p_tenant_id AND loan_id=p_loan_id) THEN RAISE EXCEPTION 'schedule already exists'; END IF;
 v_date:=v_loan.opened_on+interval '1 month'; v_remaining:=v_loan.principal;
 WHILE v_date::date<v_loan.maturity_date LOOP
  v_no:=v_no+1; v_principal_due:=bank_core.round_money(v_loan.principal / GREATEST(1,(extract(year from age(v_loan.maturity_date,v_date::date))*12+extract(month from age(v_loan.maturity_date,v_date::date)))::integer+1));
  v_interest_due:=bank_core.round_money(v_remaining*v_loan.annual_rate/12);
  INSERT INTO bank_core.installment(tenant_id,loan_id,installment_no,due_date,principal_due,interest_due,paid_amount,status)
  VALUES(p_tenant_id,p_loan_id,v_no,v_date::date,v_principal_due,v_interest_due,0,'scheduled');
  v_remaining:=v_remaining-v_principal_due; v_date:=v_date+interval '1 month';
 END LOOP;
 v_no:=v_no+1;
 INSERT INTO bank_core.installment(tenant_id,loan_id,installment_no,due_date,principal_due,interest_due,paid_amount,status)
 VALUES(p_tenant_id,p_loan_id,v_no,v_loan.maturity_date,v_remaining,bank_core.round_money(v_remaining*v_loan.annual_rate/12),0,'scheduled');
 RETURN v_no;
END $$;
