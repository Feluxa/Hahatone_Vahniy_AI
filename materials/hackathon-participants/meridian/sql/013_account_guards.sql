CREATE OR REPLACE FUNCTION bank_core.validate_account_transition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.status='closed' AND NEW.closed_on IS NULL THEN RAISE EXCEPTION 'closed account needs closed_on'; END IF;
 IF NEW.status<>'closed' AND NEW.closed_on IS NOT NULL THEN RAISE EXCEPTION 'open or blocked account cannot have closed_on'; END IF;
 IF TG_OP='UPDATE' AND OLD.status='closed' AND NEW.status<>'closed' THEN RAISE EXCEPTION 'closed account cannot reopen'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER trg_account_transition BEFORE INSERT OR UPDATE ON bank_core.account FOR EACH ROW EXECUTE FUNCTION bank_core.validate_account_transition();
CREATE OR REPLACE FUNCTION bank_core.validate_posting_account_currency() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_currency char(3); v_status text;
BEGIN SELECT currency,status INTO v_currency,v_status FROM bank_core.account WHERE tenant_id=NEW.tenant_id AND account_id=NEW.account_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'account does not exist'; END IF;
 IF NEW.currency<>v_currency THEN RAISE EXCEPTION 'posting currency differs from account currency'; END IF;
 IF NEW.status='posted' AND v_status<>'open' THEN RAISE EXCEPTION 'only open accounts accept posted entries'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER trg_posting_currency BEFORE INSERT OR UPDATE ON bank_core.posting FOR EACH ROW EXECUTE FUNCTION bank_core.validate_posting_account_currency();

