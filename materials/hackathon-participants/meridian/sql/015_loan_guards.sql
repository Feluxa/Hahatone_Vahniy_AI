CREATE OR REPLACE FUNCTION bank_core.validate_installment() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_opened date; v_maturity date; v_principal numeric(20,4); v_total numeric(20,4);
BEGIN
 SELECT opened_on,maturity_date,principal INTO v_opened,v_maturity,v_principal FROM bank_core.loan WHERE tenant_id=NEW.tenant_id AND loan_id=NEW.loan_id;
 IF NEW.due_date<=v_opened OR NEW.due_date>v_maturity THEN RAISE EXCEPTION 'installment due date outside loan term'; END IF;
 IF NEW.paid_amount>NEW.principal_due+NEW.interest_due THEN RAISE EXCEPTION 'installment cannot be overpaid'; END IF;
 SELECT COALESCE(SUM(principal_due),0) INTO v_total FROM bank_core.installment WHERE tenant_id=NEW.tenant_id AND loan_id=NEW.loan_id AND (installment_no<>NEW.installment_no OR TG_OP='INSERT');
 IF v_total+NEW.principal_due>v_principal THEN RAISE EXCEPTION 'scheduled principal exceeds loan principal'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER trg_installment_validate BEFORE INSERT OR UPDATE ON bank_core.installment FOR EACH ROW EXECUTE FUNCTION bank_core.validate_installment();
CREATE OR REPLACE FUNCTION bank_core.sync_installment_status() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 NEW.status := CASE WHEN NEW.paid_amount=0 THEN 'due' WHEN NEW.paid_amount=NEW.principal_due+NEW.interest_due THEN 'paid' ELSE 'part_paid' END;
 IF NEW.status='paid' AND NEW.paid_on IS NULL THEN NEW.paid_on:=CURRENT_DATE; END IF; RETURN NEW;
END $$;
CREATE TRIGGER trg_installment_status BEFORE INSERT OR UPDATE OF paid_amount ON bank_core.installment FOR EACH ROW EXECUTE FUNCTION bank_core.sync_installment_status();

