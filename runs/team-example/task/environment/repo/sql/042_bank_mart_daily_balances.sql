CREATE OR REPLACE FUNCTION bank_mart.refresh_daily_balances(
    p_tenant_id text,
    p_as_of_date date
)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    v_rows bigint;
BEGIN
    IF p_tenant_id IS NULL OR btrim(p_tenant_id) = '' THEN
        RAISE EXCEPTION 'tenant_id is required';
    END IF;
    IF p_as_of_date IS NULL THEN
        RAISE EXCEPTION 'as_of_date is required';
    END IF;

    PERFORM bank_mart.ensure_calendar(
        COALESCE((SELECT min(opened_on) FROM bank_core.account WHERE tenant_id = p_tenant_id), p_as_of_date),
        p_as_of_date
    );

    DELETE FROM bank_mart.daily_account_balance
    WHERE tenant_id = p_tenant_id
      AND balance_date <= p_as_of_date;

    WITH account_days AS (
        SELECT
            a.tenant_id,
            c.calendar_date AS balance_date,
            a.account_id,
            a.customer_id,
            a.currency,
            a.status AS account_status,
            a.opened_on,
            a.closed_on
        FROM bank_core.account AS a
        JOIN bank_mart.calendar_day AS c
          ON c.calendar_date >= a.opened_on
         AND c.calendar_date <= p_as_of_date
         AND (a.closed_on IS NULL OR c.calendar_date <= a.closed_on)
        WHERE a.tenant_id = p_tenant_id
    ),
    daily_postings AS (
        SELECT
            p.tenant_id,
            p.account_id,
            p.booking_date AS balance_date,
            sum(p.amount) FILTER (WHERE p.amount > 0) AS daily_credit,
            sum(p.amount) FILTER (WHERE p.amount < 0) AS daily_debit,
            sum(p.amount) AS net_movement,
            count(*)::integer AS posted_count,
            min(p.booking_date) AS first_booking_date,
            max(p.booking_date) AS last_booking_date
        FROM bank_mart.v_posted_posting AS p
        WHERE p.tenant_id = p_tenant_id
          AND p.booking_date <= p_as_of_date
        GROUP BY p.tenant_id, p.account_id, p.booking_date
    ),
    joined AS (
        SELECT
            d.tenant_id,
            d.balance_date,
            d.account_id,
            d.customer_id,
            d.currency,
            d.account_status,
            d.opened_on,
            d.closed_on,
            COALESCE(m.daily_credit, 0)::numeric(20,4) AS daily_credit,
            COALESCE(m.daily_debit, 0)::numeric(20,4) AS daily_debit,
            COALESCE(m.net_movement, 0)::numeric(20,4) AS net_movement,
            COALESCE(m.posted_count, 0) AS posted_count,
            m.first_booking_date,
            m.last_booking_date
        FROM account_days AS d
        LEFT JOIN daily_postings AS m
          ON m.tenant_id = d.tenant_id
         AND m.account_id = d.account_id
         AND m.balance_date = d.balance_date
    ),
    calculated AS (
        SELECT
            j.*,
            sum(j.net_movement) OVER (
                PARTITION BY j.tenant_id, j.account_id
                ORDER BY j.balance_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            )::numeric(20,4) AS closing_balance,
            min(j.first_booking_date) FILTER (WHERE j.first_booking_date IS NOT NULL) OVER (
                PARTITION BY j.tenant_id, j.account_id
            ) AS account_first_booking_date,
            max(j.last_booking_date) FILTER (WHERE j.last_booking_date IS NOT NULL) OVER (
                PARTITION BY j.tenant_id, j.account_id
            ) AS account_last_booking_date
        FROM joined AS j
    )
    INSERT INTO bank_mart.daily_account_balance (
        tenant_id, balance_date, account_id, customer_id, currency, account_status,
        opened_on, closed_on, daily_credit, daily_debit, net_movement, closing_balance,
        posted_count, first_booking_date, last_booking_date, refreshed_at
    )
    SELECT
        tenant_id, balance_date, account_id, customer_id, currency, account_status,
        opened_on, closed_on, daily_credit, daily_debit, net_movement, closing_balance,
        posted_count, account_first_booking_date, account_last_booking_date, clock_timestamp()
    FROM calculated;

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

CREATE OR REPLACE FUNCTION bank_mart.daily_balance(
    p_tenant_id text,
    p_account_id text,
    p_as_of_date date
)
RETURNS numeric(20,4)
LANGUAGE sql
STABLE
AS $$
    SELECT COALESCE(d.closing_balance, 0)::numeric(20,4)
    FROM bank_mart.daily_account_balance AS d
    WHERE d.tenant_id = p_tenant_id
      AND d.account_id = p_account_id
      AND d.balance_date = p_as_of_date
$$;

CREATE OR REPLACE VIEW bank_mart.v_daily_balance_summary AS
SELECT
    tenant_id,
    balance_date,
    currency,
    sum(closing_balance)::numeric(20,4) AS total_closing_balance,
    sum(daily_credit)::numeric(20,4) AS total_credit,
    sum(daily_debit)::numeric(20,4) AS total_debit,
    sum(posted_count)::bigint AS posted_count,
    count(*)::integer AS account_count
FROM bank_mart.daily_account_balance
GROUP BY tenant_id, balance_date, currency;
