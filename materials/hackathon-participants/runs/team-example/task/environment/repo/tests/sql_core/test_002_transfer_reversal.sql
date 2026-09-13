BEGIN;
INSERT INTO bank_core.tenant(tenant_id,legal_name,base_currency,operational_date) VALUES ('sql_transfer','SQL Transfer Tenant','RUB',DATE '2026-01-30');
INSERT INTO bank_core.customer(tenant_id,customer_id,display_name) VALUES ('sql_transfer','customer','Synthetic Customer');
INSERT INTO bank_core.account(tenant_id,account_id,customer_id,currency,status,opened_on) VALUES ('sql_transfer','debit','customer','RUB','open',DATE '2026-01-01'),('sql_transfer','credit','customer','RUB','open',DATE '2026-01-01');
SELECT bank_core.post_ledger_entry('sql_transfer','open','debit',DATE '2026-01-01',DATE '2026-01-01',100.0000,'RUB','test','open-key');
SELECT bank_core.post_transfer('sql_transfer','t1','debit','credit',30.0000,'RUB',DATE '2026-01-02',DATE '2026-01-02','transfer-key','test');
SELECT bank_core.post_transfer('sql_transfer','other','debit','credit',30.0000,'RUB',DATE '2026-01-02',DATE '2026-01-02','transfer-key','test');
DO $$ BEGIN IF (SELECT count(*) FROM bank_core.transfer WHERE tenant_id='sql_transfer')<>1 OR bank_core.posted_balance('sql_transfer','debit',DATE '2026-01-03')<>70 THEN RAISE EXCEPTION 'transfer failed'; END IF; END $$;
DO $$ BEGIN
 BEGIN
  PERFORM bank_core.post_transfer('sql_transfer','changed','debit','credit',31.0000,'RUB',DATE '2026-01-02',DATE '2026-01-02','transfer-key','test');
  RAISE EXCEPTION 'changed idempotent payload was accepted';
 EXCEPTION WHEN OTHERS THEN
  IF SQLERRM='changed idempotent payload was accepted' THEN RAISE; END IF;
 END;
END $$;
SELECT bank_core.reverse_transfer('sql_transfer','t1','r1',DATE '2026-01-03','reverse-key','test');
DO $$ BEGIN IF bank_core.posted_balance('sql_transfer','debit',DATE '2026-01-03')<>100 THEN RAISE EXCEPTION 'reversal failed'; END IF; END $$;
ROLLBACK;
