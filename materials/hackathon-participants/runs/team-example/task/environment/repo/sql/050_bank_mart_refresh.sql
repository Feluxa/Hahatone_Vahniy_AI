CREATE OR REPLACE FUNCTION bank_mart.refresh_tenant_mart(
    p_tenant_id text,
    p_as_of_date date,
    p_reporting_currency char(3)
)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    v_run_id bigint;
    v_source_count bigint;
    v_target_count bigint;
    v_rejected_count bigint;
BEGIN
    IF p_tenant_id IS NULL OR p_as_of_date IS NULL OR p_reporting_currency IS NULL THEN
        RAISE EXCEPTION 'tenant_id, as_of_date, and reporting_currency are required';
    END IF;

    v_run_id := bank_mart.begin_reload('tenant_mart', p_tenant_id, p_as_of_date);
    SELECT count(*) INTO v_source_count
    FROM bank_core.posting
    WHERE tenant_id = p_tenant_id
      AND booking_date <= p_as_of_date;

    BEGIN
        PERFORM bank_mart.refresh_daily_balances(p_tenant_id, p_as_of_date);
        PERFORM bank_mart.refresh_account_aging(p_tenant_id, p_as_of_date);
        PERFORM bank_mart.refresh_liquidity(p_tenant_id, p_as_of_date);
        PERFORM bank_mart.refresh_fx_exposure(p_tenant_id, p_as_of_date, p_reporting_currency);
        PERFORM bank_mart.refresh_reconciliation(p_tenant_id, p_as_of_date);
        PERFORM bank_mart.refresh_monthly_turnover(p_tenant_id, date_trunc('month', p_as_of_date)::date);
        PERFORM bank_mart.refresh_data_quality(p_tenant_id, p_as_of_date);

        SELECT count(*) INTO v_target_count
        FROM bank_mart.daily_account_balance
        WHERE tenant_id = p_tenant_id
          AND balance_date = p_as_of_date;

        SELECT coalesce(sum(affected_rows), 0) INTO v_rejected_count
        FROM bank_mart.data_quality_result
        WHERE tenant_id = p_tenant_id
          AND as_of_date = p_as_of_date
          AND severity = 'error';

        PERFORM bank_mart.finish_reload(v_run_id, v_source_count, v_target_count, v_rejected_count,
            md5(p_tenant_id || ':' || p_as_of_date::text || ':' || p_reporting_currency));
    EXCEPTION WHEN OTHERS THEN
        PERFORM bank_mart.fail_reload(v_run_id, SQLERRM);
        RAISE;
    END;
    RETURN v_run_id;
END;
$$;

CREATE OR REPLACE FUNCTION bank_mart.refresh_all_tenants(p_as_of_date date, p_reporting_currency char(3))
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    v_tenant record;
    v_runs bigint := 0;
BEGIN
    FOR v_tenant IN SELECT DISTINCT tenant_id FROM bank_core.account ORDER BY tenant_id LOOP
        PERFORM bank_mart.refresh_tenant_mart(v_tenant.tenant_id, p_as_of_date, p_reporting_currency);
        v_runs := v_runs + 1;
    END LOOP;
    RETURN v_runs;
END;
$$;
