CREATE OR REPLACE FUNCTION bank_mart.refresh_fx_exposure(p_tenant_id text, p_as_of_date date, p_reporting_currency char(3))
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE v_rows bigint;
BEGIN
  IF p_tenant_id IS NULL OR p_as_of_date IS NULL OR p_reporting_currency IS NULL THEN RAISE EXCEPTION 'tenant, as_of and reporting currency are required'; END IF;
  PERFORM bank_mart.refresh_daily_balances(p_tenant_id,p_as_of_date);
  DELETE FROM bank_mart.fx_exposure_snapshot WHERE tenant_id=p_tenant_id AND as_of_date=p_as_of_date AND reporting_currency=p_reporting_currency;
  WITH currency_balances AS (
    SELECT tenant_id,currency,sum(closing_balance)::numeric(20,4) AS native_balance,count(*)::integer AS account_count
    FROM bank_mart.daily_account_balance WHERE tenant_id=p_tenant_id AND balance_date=p_as_of_date GROUP BY tenant_id,currency
  ), selected_rate AS (
    SELECT cb.tenant_id,cb.currency,cb.native_balance,cb.account_count,
      CASE WHEN cb.currency=p_reporting_currency THEN 1::numeric(20,8) ELSE r.rate END AS fx_rate
    FROM currency_balances cb LEFT JOIN bank_core.fx_rate r
      ON r.rate_date=p_as_of_date AND r.from_currency=cb.currency AND r.to_currency=p_reporting_currency
  )
  INSERT INTO bank_mart.fx_exposure_snapshot (
     tenant_id,as_of_date,reporting_currency,currency,native_balance,fx_rate,reporting_balance,rate_status,account_count,refreshed_at
  )
  SELECT tenant_id,p_as_of_date,p_reporting_currency,currency,native_balance,fx_rate,
    CASE WHEN fx_rate IS NULL THEN NULL ELSE round(native_balance*fx_rate,4) END,
    CASE WHEN currency=p_reporting_currency THEN 'native' WHEN fx_rate IS NULL THEN 'missing_rate' ELSE 'rated' END,
    account_count,clock_timestamp() FROM selected_rate;
  GET DIAGNOSTICS v_rows=ROW_COUNT; RETURN v_rows;
END; $$;

CREATE OR REPLACE VIEW bank_mart.v_fx_exposure_summary AS
SELECT tenant_id,as_of_date,reporting_currency,
  sum(reporting_balance) FILTER (WHERE rate_status IN ('native','rated'))::numeric(20,4) AS rated_total,
  count(*) FILTER (WHERE rate_status='missing_rate')::integer AS missing_rate_currency_count
FROM bank_mart.fx_exposure_snapshot GROUP BY tenant_id,as_of_date,reporting_currency;
