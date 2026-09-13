CREATE TABLE IF NOT EXISTS bank_mart.cashflow_projection (
    tenant_id text NOT NULL,
    as_of_date date NOT NULL,
    projected_date date NOT NULL,
    currency char(3) NOT NULL,
    opening_liquidity numeric(20,4) NOT NULL,
    expected_loan_inflow numeric(20,4) NOT NULL,
    historical_net_flow numeric(20,4) NOT NULL,
    projected_closing_liquidity numeric(20,4) NOT NULL,
    installment_count integer NOT NULL,
    refreshed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, as_of_date, projected_date, currency)
);

CREATE OR REPLACE FUNCTION bank_mart.refresh_cashflow_projection(
    p_tenant_id text,
    p_as_of_date date,
    p_horizon_days integer DEFAULT 30
)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    v_rows bigint;
BEGIN
    IF p_tenant_id IS NULL OR p_as_of_date IS NULL OR p_horizon_days < 1 OR p_horizon_days > 366 THEN
        RAISE EXCEPTION 'tenant, as_of date, and horizon from 1 to 366 are required';
    END IF;
    PERFORM bank_mart.refresh_daily_balances(p_tenant_id, p_as_of_date);
    DELETE FROM bank_mart.cashflow_projection
    WHERE tenant_id = p_tenant_id
      AND as_of_date = p_as_of_date;

    WITH currencies AS (
        SELECT DISTINCT currency FROM bank_core.account WHERE tenant_id = p_tenant_id
    ), dates AS (
        SELECT d::date AS projected_date
        FROM generate_series(p_as_of_date + 1, p_as_of_date + p_horizon_days, interval '1 day') AS g(d)
    ), opening AS (
        SELECT currency, sum(closing_balance)::numeric(20,4) AS opening_liquidity
        FROM bank_mart.daily_account_balance
        WHERE tenant_id = p_tenant_id AND balance_date = p_as_of_date
        GROUP BY currency
    ), loan_due AS (
        SELECT a.currency, i.due_date AS projected_date,
               sum(i.principal_due + i.interest_due - i.paid_amount)::numeric(20,4) AS expected_loan_inflow,
               count(*)::integer AS installment_count
        FROM bank_core.loan l
        JOIN bank_core.account a ON a.tenant_id=l.tenant_id AND a.account_id=l.account_id
        JOIN bank_core.installment i ON i.tenant_id=l.tenant_id AND i.loan_id=l.loan_id
        WHERE l.tenant_id=p_tenant_id AND i.due_date BETWEEN p_as_of_date+1 AND p_as_of_date+p_horizon_days
        GROUP BY a.currency,i.due_date
    ), historical AS (
        SELECT currency, coalesce(avg(net_movement),0)::numeric(20,4) AS historical_net_flow
        FROM bank_mart.daily_account_balance
        WHERE tenant_id=p_tenant_id AND balance_date BETWEEN greatest(p_as_of_date-30, date '1900-01-01') AND p_as_of_date
        GROUP BY currency
    ), grid AS (
        SELECT c.currency,d.projected_date,coalesce(o.opening_liquidity,0)::numeric(20,4) opening_liquidity,
          coalesce(l.expected_loan_inflow,0)::numeric(20,4) expected_loan_inflow,coalesce(h.historical_net_flow,0)::numeric(20,4) historical_net_flow,coalesce(l.installment_count,0) installment_count
        FROM currencies c CROSS JOIN dates d LEFT JOIN opening o ON o.currency=c.currency LEFT JOIN loan_due l ON l.currency=c.currency AND l.projected_date=d.projected_date LEFT JOIN historical h ON h.currency=c.currency
    )
    INSERT INTO bank_mart.cashflow_projection(tenant_id,as_of_date,projected_date,currency,opening_liquidity,expected_loan_inflow,historical_net_flow,projected_closing_liquidity,installment_count,refreshed_at)
    SELECT p_tenant_id,p_as_of_date,projected_date,currency,opening_liquidity,expected_loan_inflow,historical_net_flow,
      (opening_liquidity + sum(expected_loan_inflow+historical_net_flow) OVER(PARTITION BY currency ORDER BY projected_date))::numeric(20,4),installment_count,clock_timestamp() FROM grid;
    GET DIAGNOSTICS v_rows=ROW_COUNT; RETURN v_rows;
END; $$;

CREATE OR REPLACE VIEW bank_mart.v_cashflow_projection_summary AS
SELECT tenant_id,as_of_date,projected_date,currency,projected_closing_liquidity,expected_loan_inflow,historical_net_flow FROM bank_mart.cashflow_projection;
