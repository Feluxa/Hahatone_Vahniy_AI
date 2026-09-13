CREATE OR REPLACE FUNCTION bank_mart.refresh_liquidity(p_tenant_id text, p_as_of_date date)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE v_rows bigint;
BEGIN
  IF p_tenant_id IS NULL OR p_as_of_date IS NULL THEN RAISE EXCEPTION 'tenant_id and as_of_date are required'; END IF;
  PERFORM bank_mart.refresh_daily_balances(p_tenant_id, p_as_of_date);
  DELETE FROM bank_mart.liquidity_snapshot WHERE tenant_id=p_tenant_id AND as_of_date=p_as_of_date;
  WITH balances AS (
    SELECT tenant_id, currency, account_id, closing_balance, daily_credit, daily_debit
    FROM bank_mart.daily_account_balance WHERE tenant_id=p_tenant_id AND balance_date=p_as_of_date
  ), ranked AS (
    SELECT b.*, row_number() OVER (PARTITION BY tenant_id,currency ORDER BY closing_balance DESC, account_id) AS balance_rank
    FROM balances b
  ), aggregate_rows AS (
    SELECT tenant_id, currency,
      coalesce(sum(closing_balance),0)::numeric(20,4) AS total_balance,
      coalesce(sum(daily_credit),0)::numeric(20,4) AS credit_today,
      coalesce(sum(daily_debit),0)::numeric(20,4) AS debit_today,
      count(*)::integer AS active_accounts,
      count(*) FILTER (WHERE closing_balance < 0)::integer AS negative_accounts,
      coalesce(sum(closing_balance) FILTER (WHERE balance_rank <= 5),0)::numeric(20,4) AS concentration_top5
    FROM ranked GROUP BY tenant_id,currency
  )
  INSERT INTO bank_mart.liquidity_snapshot (
     tenant_id,as_of_date,currency,total_balance,credit_today,debit_today,net_today,
     active_accounts,negative_accounts,concentration_top5,refreshed_at
  )
  SELECT tenant_id,p_as_of_date,currency,total_balance,credit_today,debit_today,
     (credit_today+debit_today)::numeric(20,4),active_accounts,negative_accounts,concentration_top5,clock_timestamp()
  FROM aggregate_rows;
  GET DIAGNOSTICS v_rows=ROW_COUNT; RETURN v_rows;
END; $$;

CREATE OR REPLACE VIEW bank_mart.v_liquidity_concentration AS
SELECT l.*, CASE WHEN total_balance=0 THEN NULL ELSE round(concentration_top5 / total_balance, 8) END AS top5_ratio
FROM bank_mart.liquidity_snapshot l;
