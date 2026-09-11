CREATE OR REPLACE FUNCTION bank_mart.prune_reload_audit(p_before date)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE v_rows bigint;
BEGIN
 IF p_before IS NULL THEN RAISE EXCEPTION 'before date is required'; END IF;
 DELETE FROM bank_mart.reload_run WHERE requested_as_of<p_before AND status IN ('succeeded','failed');
 GET DIAGNOSTICS v_rows=ROW_COUNT; RETURN v_rows;
END; $$;

CREATE OR REPLACE FUNCTION bank_mart.prune_snapshots(p_before date)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE v_rows bigint:=0; v_deleted bigint;
BEGIN
 IF p_before IS NULL THEN RAISE EXCEPTION 'before date is required'; END IF;
 DELETE FROM bank_mart.daily_account_balance WHERE balance_date<p_before; GET DIAGNOSTICS v_deleted=ROW_COUNT; v_rows:=v_rows+v_deleted;
 DELETE FROM bank_mart.account_aging_snapshot WHERE as_of_date<p_before; GET DIAGNOSTICS v_deleted=ROW_COUNT; v_rows:=v_rows+v_deleted;
 DELETE FROM bank_mart.liquidity_snapshot WHERE as_of_date<p_before; GET DIAGNOSTICS v_deleted=ROW_COUNT; v_rows:=v_rows+v_deleted;
 DELETE FROM bank_mart.fx_exposure_snapshot WHERE as_of_date<p_before; GET DIAGNOSTICS v_deleted=ROW_COUNT; v_rows:=v_rows+v_deleted;
 DELETE FROM bank_mart.reconciliation_snapshot WHERE as_of_date<p_before; GET DIAGNOSTICS v_deleted=ROW_COUNT; v_rows:=v_rows+v_deleted;
 DELETE FROM bank_mart.loan_performance_snapshot WHERE as_of_date<p_before; GET DIAGNOSTICS v_deleted=ROW_COUNT; v_rows:=v_rows+v_deleted;
 DELETE FROM bank_mart.cashflow_projection WHERE as_of_date<p_before; GET DIAGNOSTICS v_deleted=ROW_COUNT; v_rows:=v_rows+v_deleted;
 DELETE FROM bank_mart.customer_position_snapshot WHERE as_of_date<p_before; GET DIAGNOSTICS v_deleted=ROW_COUNT; v_rows:=v_rows+v_deleted;
 RETURN v_rows;
END; $$;

-- TODO(MART-311): move retention periods to an approved configuration contract; callers supply the explicit date today.
