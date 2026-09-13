BEGIN;
INSERT INTO bank_core.tenant(tenant_id,legal_name,base_currency,operational_date) VALUES ('sql_contract','SQL Contract Tenant','RUB',DATE '2026-01-30');
INSERT INTO bank_core.customer(tenant_id,customer_id,display_name) VALUES ('sql_contract','customer','Synthetic Customer');
INSERT INTO bank_core.account(tenant_id,account_id,customer_id,currency,status,opened_on) VALUES ('sql_contract','a','customer','RUB','open',DATE '2026-01-01');
INSERT INTO bank_core.posting(tenant_id,posting_id,account_id,booking_date,value_date,amount,currency,status,reversal_of,source_system) VALUES ('sql_contract','p','a',DATE '2026-01-03',DATE '2026-01-03',12.3456,'RUB','posted',NULL,'test');
DO $$ BEGIN IF (SELECT booked_balance FROM bank_core.account_balance WHERE tenant_id='sql_contract' AND account_id='a')<>12.3456 THEN RAISE EXCEPTION 'posted balance failed'; END IF; END $$;
ROLLBACK;

