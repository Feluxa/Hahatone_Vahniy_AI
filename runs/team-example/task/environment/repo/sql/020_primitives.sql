CREATE OR REPLACE FUNCTION bank_core.require_tenant(p_tenant_id text) RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
 IF p_tenant_id IS NULL OR btrim(p_tenant_id)='' THEN
  RAISE EXCEPTION 'tenant_id is required';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM bank_core.tenant WHERE tenant_id=p_tenant_id) THEN
  RAISE EXCEPTION 'unknown tenant %',p_tenant_id;
 END IF;
END $$;

CREATE OR REPLACE FUNCTION bank_core.round_money(p_value numeric) RETURNS numeric(20,4)
LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$ SELECT round(p_value,4)::numeric(20,4) $$;

CREATE OR REPLACE FUNCTION bank_core.next_business_date(p_date date) RETURNS date
LANGUAGE plpgsql STABLE
AS $$
DECLARE v_date date := p_date;
 v_candidate date;
BEGIN
 IF p_date IS NULL THEN RAISE EXCEPTION 'business date is required'; END IF;
 LOOP
  SELECT calendar_date INTO v_candidate FROM bank_core.calendar_day
  WHERE calendar_date>=v_date AND is_business_day ORDER BY calendar_date LIMIT 1;
  IF v_candidate IS NOT NULL THEN RETURN v_candidate; END IF;
  IF v_date>=p_date+14 THEN RAISE EXCEPTION 'calendar is incomplete after %',p_date; END IF;
  v_date:=v_date+1;
 END LOOP;
END $$;

-- TODO: Availability holds need an explicit product table; booked ledger balance deliberately excludes them.

CREATE OR REPLACE FUNCTION bank_core.posted_balance(p_tenant_id text,p_account_id text,p_as_of_date date DEFAULT NULL)
RETURNS numeric(20,4) LANGUAGE plpgsql STABLE AS $$
DECLARE v_balance numeric(20,4);
BEGIN
 PERFORM bank_core.require_tenant(p_tenant_id);
 SELECT COALESCE(SUM(amount) FILTER (WHERE status='posted'),0)::numeric(20,4) INTO v_balance
 FROM bank_core.posting WHERE tenant_id=p_tenant_id AND account_id=p_account_id
 AND (p_as_of_date IS NULL OR value_date<=p_as_of_date);
 RETURN v_balance;
END $$;

CREATE OR REPLACE FUNCTION bank_core.assert_currency(p_currency char(3)) RETURNS void
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
 IF p_currency IS NULL OR p_currency !~ '^[A-Z]{3}$' THEN
  RAISE EXCEPTION 'invalid ISO currency %',p_currency;
 END IF;
END $$;

CREATE OR REPLACE FUNCTION bank_core.assert_positive_money(p_amount numeric,p_name text) RETURNS void
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
 IF p_amount IS NULL OR p_amount<=0 THEN RAISE EXCEPTION '% must be positive',p_name; END IF;
 IF scale(p_amount)>4 THEN RAISE EXCEPTION '% exceeds four decimal places',p_name; END IF;
END $$;
