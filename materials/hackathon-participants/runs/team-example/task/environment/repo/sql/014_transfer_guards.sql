CREATE OR REPLACE FUNCTION bank_core.validate_transfer_accounts() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE debit_currency char(3); credit_currency char(3); debit_status text; credit_status text;
BEGIN
 SELECT currency,status INTO debit_currency,debit_status FROM bank_core.account WHERE tenant_id=NEW.tenant_id AND account_id=NEW.debit_account_id;
 SELECT currency,status INTO credit_currency,credit_status FROM bank_core.account WHERE tenant_id=NEW.tenant_id AND account_id=NEW.credit_account_id;
 IF debit_currency IS NULL OR credit_currency IS NULL THEN RAISE EXCEPTION 'transfer account missing'; END IF;
 IF debit_currency<>NEW.currency OR credit_currency<>NEW.currency THEN RAISE EXCEPTION 'transfer currency mismatch'; END IF;
 IF NEW.status IN ('validated','posted') AND (debit_status<>'open' OR credit_status<>'open') THEN RAISE EXCEPTION 'transfer requires open accounts'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER trg_transfer_accounts BEFORE INSERT OR UPDATE ON bank_core.transfer FOR EACH ROW EXECUTE FUNCTION bank_core.validate_transfer_accounts();
CREATE OR REPLACE FUNCTION bank_core.record_transfer_event() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_no integer;
BEGIN SELECT COALESCE(MAX(event_no),0)+1 INTO v_no FROM bank_core.transfer_event WHERE tenant_id=NEW.tenant_id AND transfer_id=NEW.transfer_id;
 INSERT INTO bank_core.transfer_event(tenant_id,transfer_id,event_no,event_type,actor) VALUES(NEW.tenant_id,NEW.transfer_id,v_no,NEW.status,current_user);
 RETURN NEW;
END $$;
CREATE TRIGGER trg_transfer_event AFTER INSERT OR UPDATE OF status ON bank_core.transfer FOR EACH ROW EXECUTE FUNCTION bank_core.record_transfer_event();

