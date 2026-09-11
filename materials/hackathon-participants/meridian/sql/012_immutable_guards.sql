CREATE OR REPLACE FUNCTION bank_core.prevent_posted_amount_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.status='posted' AND (NEW.amount,NEW.currency,NEW.account_id,NEW.value_date) IS DISTINCT FROM (OLD.amount,OLD.currency,OLD.account_id,OLD.value_date) THEN
  RAISE EXCEPTION 'posted ledger attributes are immutable';
 END IF;
 IF OLD.status='void' AND NEW IS DISTINCT FROM OLD THEN RAISE EXCEPTION 'void posting is immutable'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER trg_posting_immutable BEFORE UPDATE ON bank_core.posting FOR EACH ROW EXECUTE FUNCTION bank_core.prevent_posted_amount_change();
CREATE OR REPLACE FUNCTION bank_core.record_posting_status() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='INSERT' OR OLD.status IS DISTINCT FROM NEW.status THEN
  INSERT INTO bank_core.posting_status_history(tenant_id,posting_id,old_status,new_status,changed_by)
  VALUES(NEW.tenant_id,NEW.posting_id,CASE WHEN TG_OP='INSERT' THEN NULL ELSE OLD.status END,NEW.status,current_user);
 END IF; RETURN NEW;
END $$;
CREATE TRIGGER trg_posting_status AFTER INSERT OR UPDATE ON bank_core.posting FOR EACH ROW EXECUTE FUNCTION bank_core.record_posting_status();

