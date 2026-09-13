CREATE TABLE IF NOT EXISTS bank_mart.loan_performance_snapshot (
    tenant_id text NOT NULL,
    as_of_date date NOT NULL,
    loan_id text NOT NULL,
    customer_id text NOT NULL,
    account_id text NOT NULL,
    currency char(3) NOT NULL,
    loan_status text NOT NULL,
    principal numeric(20,4) NOT NULL,
    scheduled_due numeric(20,4) NOT NULL,
    paid_amount numeric(20,4) NOT NULL,
    unpaid_amount numeric(20,4) NOT NULL,
    overdue_amount numeric(20,4) NOT NULL,
    oldest_due_date date,
    days_past_due integer NOT NULL,
    delinquency_bucket text NOT NULL,
    refreshed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, as_of_date, loan_id),
    CONSTRAINT loan_performance_math CHECK (unpaid_amount = scheduled_due - paid_amount),
    CONSTRAINT loan_performance_bucket CHECK (delinquency_bucket IN ('current', '1_30', '31_60', '61_90', 'over_90'))
);

CREATE INDEX IF NOT EXISTS loan_performance_snapshot_lookup_idx
    ON bank_mart.loan_performance_snapshot (tenant_id, as_of_date, currency, delinquency_bucket);

CREATE OR REPLACE FUNCTION bank_mart.refresh_loan_performance(p_tenant_id text, p_as_of_date date)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    v_rows bigint;
BEGIN
    IF p_tenant_id IS NULL OR p_as_of_date IS NULL THEN
        RAISE EXCEPTION 'tenant_id and as_of_date are required';
    END IF;

    DELETE FROM bank_mart.loan_performance_snapshot
    WHERE tenant_id = p_tenant_id
      AND as_of_date = p_as_of_date;

    WITH scheduled AS (
        SELECT
            l.tenant_id,
            l.loan_id,
            l.customer_id,
            l.account_id,
            a.currency,
            l.status AS loan_status,
            l.principal,
            i.installment_no,
            i.due_date,
            (i.principal_due + i.interest_due)::numeric(20,4) AS installment_due,
            i.paid_amount::numeric(20,4) AS paid_amount
        FROM bank_core.loan AS l
        JOIN bank_core.account AS a
          ON a.tenant_id = l.tenant_id
         AND a.account_id = l.account_id
        LEFT JOIN bank_core.installment AS i
          ON i.tenant_id = l.tenant_id
         AND i.loan_id = l.loan_id
         AND i.due_date <= p_as_of_date
        WHERE l.tenant_id = p_tenant_id
          AND l.opened_on <= p_as_of_date
    ), aggregates AS (
        SELECT
            tenant_id,
            loan_id,
            customer_id,
            account_id,
            currency,
            loan_status,
            principal,
            coalesce(sum(installment_due), 0)::numeric(20,4) AS scheduled_due,
            coalesce(sum(paid_amount), 0)::numeric(20,4) AS paid_amount,
            coalesce(sum(greatest(installment_due - paid_amount, 0)) FILTER (WHERE due_date < p_as_of_date), 0)::numeric(20,4) AS overdue_amount,
            min(due_date) FILTER (WHERE installment_due > paid_amount AND due_date < p_as_of_date) AS oldest_due_date
        FROM scheduled
        GROUP BY tenant_id, loan_id, customer_id, account_id, currency, loan_status, principal
    ), classified AS (
        SELECT
            a.*,
            greatest(scheduled_due - paid_amount, 0)::numeric(20,4) AS unpaid_amount,
            CASE
                WHEN oldest_due_date IS NULL THEN 0
                ELSE p_as_of_date - oldest_due_date
            END AS days_past_due
        FROM aggregates AS a
    )
    INSERT INTO bank_mart.loan_performance_snapshot (
        tenant_id, as_of_date, loan_id, customer_id, account_id, currency, loan_status,
        principal, scheduled_due, paid_amount, unpaid_amount, overdue_amount,
        oldest_due_date, days_past_due, delinquency_bucket, refreshed_at
    )
    SELECT
        tenant_id, p_as_of_date, loan_id, customer_id, account_id, currency, loan_status,
        principal, scheduled_due, paid_amount, unpaid_amount, overdue_amount,
        oldest_due_date, days_past_due,
        CASE
            WHEN days_past_due = 0 THEN 'current'
            WHEN days_past_due <= 30 THEN '1_30'
            WHEN days_past_due <= 60 THEN '31_60'
            WHEN days_past_due <= 90 THEN '61_90'
            ELSE 'over_90'
        END,
        clock_timestamp()
    FROM classified;

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

CREATE OR REPLACE VIEW bank_mart.v_loan_delinquency_summary AS
SELECT
    tenant_id,
    as_of_date,
    currency,
    delinquency_bucket,
    count(*)::integer AS loan_count,
    sum(principal)::numeric(20,4) AS principal_total,
    sum(overdue_amount)::numeric(20,4) AS overdue_total,
    sum(unpaid_amount)::numeric(20,4) AS unpaid_total
FROM bank_mart.loan_performance_snapshot
GROUP BY tenant_id, as_of_date, currency, delinquency_bucket;

CREATE OR REPLACE FUNCTION bank_mart.loan_delinquency_ratio(p_tenant_id text, p_as_of_date date, p_currency char(3))
RETURNS numeric(20,8)
LANGUAGE sql
STABLE
AS $$
    SELECT CASE
        WHEN coalesce(sum(principal), 0) = 0 THEN 0::numeric(20,8)
        ELSE round(coalesce(sum(overdue_amount), 0) / sum(principal), 8)
    END
    FROM bank_mart.loan_performance_snapshot
    WHERE tenant_id = p_tenant_id
      AND as_of_date = p_as_of_date
      AND currency = p_currency
$$;

-- TODO(MART-267): add an approved synthetic write-off feed when core publishes a write-off contract.
