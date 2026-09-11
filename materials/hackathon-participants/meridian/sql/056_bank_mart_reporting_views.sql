CREATE OR REPLACE VIEW bank_mart.v_tenant_operating_dashboard AS
SELECT
  l.tenant_id,l.as_of_date,l.currency,l.total_balance,l.net_today,l.active_accounts,l.negative_accounts,
  coalesce(r.variance,0)::numeric(20,4) AS reconciliation_variance,
  coalesce(q.error_rows,0)::bigint AS data_quality_error_rows,
  coalesce(e.open_exception_count,0)::bigint AS open_exception_count
FROM bank_mart.liquidity_snapshot l
LEFT JOIN bank_mart.reconciliation_snapshot r ON r.tenant_id=l.tenant_id AND r.as_of_date=l.as_of_date AND r.currency=l.currency
LEFT JOIN (SELECT tenant_id,as_of_date,sum(affected_rows) FILTER(WHERE severity='error') error_rows FROM bank_mart.data_quality_result GROUP BY tenant_id,as_of_date) q ON q.tenant_id=l.tenant_id AND q.as_of_date=l.as_of_date
LEFT JOIN (SELECT tenant_id,as_of_date,count(*) open_exception_count FROM bank_mart.exception_queue WHERE state='open' GROUP BY tenant_id,as_of_date) e ON e.tenant_id=l.tenant_id AND e.as_of_date=l.as_of_date;

CREATE OR REPLACE VIEW bank_mart.v_account_activity AS
SELECT d.tenant_id,d.account_id,d.customer_id,d.balance_date,d.currency,d.daily_credit,d.daily_debit,d.net_movement,d.closing_balance,d.posted_count,
  lag(d.closing_balance) OVER(PARTITION BY d.tenant_id,d.account_id ORDER BY d.balance_date) prior_closing_balance,
  sum(d.net_movement) OVER(PARTITION BY d.tenant_id,d.account_id ORDER BY d.balance_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)::numeric(20,4) rolling_seven_day_movement
FROM bank_mart.daily_account_balance d;

CREATE OR REPLACE VIEW bank_mart.v_account_month_end_balance AS
SELECT DISTINCT ON (tenant_id,account_id,date_trunc('month',balance_date)) tenant_id,account_id,customer_id,currency,date_trunc('month',balance_date)::date month_start,balance_date month_end_date,closing_balance
FROM bank_mart.daily_account_balance ORDER BY tenant_id,account_id,date_trunc('month',balance_date),balance_date DESC;

CREATE OR REPLACE VIEW bank_mart.v_unrated_fx_exposure AS SELECT * FROM bank_mart.fx_exposure_snapshot WHERE rate_status='missing_rate';
