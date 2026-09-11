CREATE OR REPLACE FUNCTION bank_mart.refresh_data_quality(p_tenant_id text, p_as_of_date date)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    v_rows bigint;
BEGIN
    IF p_tenant_id IS NULL OR btrim(p_tenant_id) = '' OR p_as_of_date IS NULL THEN
        RAISE EXCEPTION 'tenant_id and as_of_date are required';
    END IF;

    DELETE FROM bank_mart.data_quality_result
    WHERE tenant_id = p_tenant_id
      AND as_of_date = p_as_of_date;

    WITH rules AS (
        SELECT
            'ACCOUNT_CURRENCY_POSTING_CURRENCY'::text AS rule_code,
            'error'::text AS severity,
            count(*)::bigint AS affected_rows,
            min(p.account_id || ':' || p.posting_id) AS sample_key,
            min(p.currency)::text AS observed_value,
            min(a.currency)::text AS expected_value
        FROM bank_core.posting AS p
        JOIN bank_core.account AS a
          ON a.tenant_id = p.tenant_id
         AND a.account_id = p.account_id
        WHERE p.tenant_id = p_tenant_id
          AND p.booking_date <= p_as_of_date
          AND p.currency <> a.currency

        UNION ALL

        SELECT
            'POSTING_BEFORE_ACCOUNT_OPEN'::text,
            'error'::text,
            count(*)::bigint,
            min(p.account_id || ':' || p.posting_id),
            min(p.booking_date)::text,
            min(a.opened_on)::text
        FROM bank_core.posting AS p
        JOIN bank_core.account AS a
          ON a.tenant_id = p.tenant_id
         AND a.account_id = p.account_id
        WHERE p.tenant_id = p_tenant_id
          AND p.booking_date <= p_as_of_date
          AND p.booking_date < a.opened_on

        UNION ALL

        SELECT
            'POSTING_AFTER_ACCOUNT_CLOSE'::text,
            'warning'::text,
            count(*)::bigint,
            min(p.account_id || ':' || p.posting_id),
            min(p.booking_date)::text,
            min(a.closed_on)::text
        FROM bank_core.posting AS p
        JOIN bank_core.account AS a
          ON a.tenant_id = p.tenant_id
         AND a.account_id = p.account_id
        WHERE p.tenant_id = p_tenant_id
          AND p.booking_date <= p_as_of_date
          AND a.closed_on IS NOT NULL
          AND p.booking_date > a.closed_on

        UNION ALL

        SELECT
            'POSTING_VALUE_DATE_BEFORE_BOOKING'::text,
            'warning'::text,
            count(*)::bigint,
            min(account_id || ':' || posting_id),
            min(value_date)::text,
            min(booking_date)::text
        FROM bank_core.posting
        WHERE tenant_id = p_tenant_id
          AND booking_date <= p_as_of_date
          AND value_date < booking_date

        UNION ALL

        SELECT
            'REVERSAL_TARGET_NOT_FOUND'::text,
            'warning'::text,
            count(*)::bigint,
            min(p.account_id || ':' || p.posting_id),
            min(p.reversal_of),
            'existing posting_id'::text
        FROM bank_core.posting AS p
        LEFT JOIN bank_core.posting AS original
          ON original.tenant_id = p.tenant_id
         AND original.posting_id = p.reversal_of
        WHERE p.tenant_id = p_tenant_id
          AND p.booking_date <= p_as_of_date
          AND p.reversal_of IS NOT NULL
          AND original.posting_id IS NULL

        UNION ALL

        SELECT
            'MISSING_FX_RATE_FOR_OPEN_BALANCE'::text,
            'info'::text,
            count(*)::bigint,
            min(d.account_id),
            min(d.currency)::text,
            'rate to reporting currency selected by consumer'::text
        FROM bank_mart.daily_account_balance AS d
        WHERE d.tenant_id = p_tenant_id
          AND d.balance_date = p_as_of_date
          AND d.closing_balance <> 0
    )
    INSERT INTO bank_mart.data_quality_result (
        tenant_id, as_of_date, rule_code, severity, affected_rows,
        sample_key, observed_value, expected_value, checked_at
    )
    SELECT
        p_tenant_id, p_as_of_date, rule_code, severity, affected_rows,
        sample_key, observed_value, expected_value, clock_timestamp()
    FROM rules;

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

CREATE OR REPLACE VIEW bank_mart.v_data_quality_open_issues AS
SELECT *
FROM bank_mart.data_quality_result
WHERE affected_rows > 0;

CREATE OR REPLACE FUNCTION bank_mart.data_quality_error_count(p_tenant_id text, p_as_of_date date)
RETURNS bigint
LANGUAGE sql
STABLE
AS $$
    SELECT coalesce(sum(affected_rows), 0)
    FROM bank_mart.data_quality_result
    WHERE tenant_id = p_tenant_id
      AND as_of_date = p_as_of_date
      AND severity = 'error'
$$;
