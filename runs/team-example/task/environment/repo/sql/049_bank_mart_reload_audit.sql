CREATE OR REPLACE FUNCTION bank_mart.begin_reload(
    p_mart_name text,
    p_tenant_id text,
    p_as_of_date date
)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    v_run_id bigint;
BEGIN
    IF p_mart_name IS NULL OR btrim(p_mart_name) = '' THEN
        RAISE EXCEPTION 'mart_name is required';
    END IF;
    IF p_as_of_date IS NULL THEN
        RAISE EXCEPTION 'as_of_date is required';
    END IF;

    UPDATE bank_mart.reload_run
    SET status = 'failed',
        finished_at = clock_timestamp(),
        error_message = 'superseded by a subsequent bounded reload'
    WHERE mart_name = p_mart_name
      AND tenant_id IS NOT DISTINCT FROM p_tenant_id
      AND requested_as_of = p_as_of_date
      AND status = 'running';

    INSERT INTO bank_mart.reload_run (
        mart_name, tenant_id, requested_as_of, started_at, status, requested_by
    )
    VALUES (
        p_mart_name, p_tenant_id, p_as_of_date, clock_timestamp(), 'running', current_user
    )
    RETURNING run_id INTO v_run_id;

    RETURN v_run_id;
END;
$$;

CREATE OR REPLACE FUNCTION bank_mart.finish_reload(
    p_run_id bigint,
    p_source_row_count bigint,
    p_target_row_count bigint,
    p_rejected_row_count bigint,
    p_checksum text DEFAULT NULL
)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_run_id IS NULL THEN
        RAISE EXCEPTION 'run_id is required';
    END IF;
    IF coalesce(p_source_row_count, -1) < 0
       OR coalesce(p_target_row_count, -1) < 0
       OR coalesce(p_rejected_row_count, -1) < 0 THEN
        RAISE EXCEPTION 'reload counts must be non-negative';
    END IF;

    UPDATE bank_mart.reload_run
    SET source_row_count = p_source_row_count,
        target_row_count = p_target_row_count,
        rejected_row_count = p_rejected_row_count,
        checksum = p_checksum,
        status = 'succeeded',
        finished_at = clock_timestamp(),
        error_message = NULL
    WHERE run_id = p_run_id
      AND status = 'running';

    IF NOT FOUND THEN
        RAISE EXCEPTION 'reload run % is not active', p_run_id;
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION bank_mart.fail_reload(p_run_id bigint, p_error_message text)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE bank_mart.reload_run
    SET status = 'failed',
        finished_at = clock_timestamp(),
        error_message = left(coalesce(p_error_message, 'unspecified warehouse failure'), 2000)
    WHERE run_id = p_run_id
      AND status = 'running';

    IF NOT FOUND THEN
        RAISE EXCEPTION 'reload run % is not active', p_run_id;
    END IF;
END;
$$;

CREATE OR REPLACE VIEW bank_mart.v_reload_audit AS
SELECT
    run_id, mart_name, tenant_id, requested_as_of, started_at, finished_at, status,
    source_row_count, target_row_count, rejected_row_count, checksum, requested_by,
    error_message,
    CASE WHEN finished_at IS NULL THEN NULL ELSE finished_at - started_at END AS elapsed
FROM bank_mart.reload_run;

-- TODO(MART-231): define a service-owned actor identifier after identity integration.
-- Legacy path (2024-11): per-table audit logs were proposed. Active-legacy decision (2025-03): retain one normalized run ledger.
