BEGIN;
SET LOCAL statement_timeout='1000ms';
INSERT INTO bank_core.tenant(tenant_id,legal_name,base_currency,operational_date) VALUES ('sql_ingest','SQL Ingest Tenant','RUB',DATE '2026-01-30');
INSERT INTO bank_core.customer(tenant_id,customer_id,display_name) VALUES ('sql_ingest','customer','Synthetic Customer');
INSERT INTO bank_core.account(tenant_id,account_id,customer_id,currency,status,opened_on) VALUES
 ('sql_ingest','debit','customer','RUB','open',DATE '2026-01-01'),('sql_ingest','credit','customer','RUB','open',DATE '2026-01-01');
SELECT bank_core.post_ledger_entry('sql_ingest','opening','debit',DATE '2026-01-01',DATE '2026-01-01',100.0000,'RUB','test','opening');
SELECT bank_core.ingest_transfer_message('sql_ingest','message-1','message-key','test',
 '{"transfer_id":"ingest-1","debit_account_id":"debit","credit_account_id":"credit","amount":"25.0000","currency":"RUB","booking_date":"2026-01-02","value_date":"2026-01-02"}');
SELECT bank_core.ingest_transfer_message('sql_ingest','message-replay','message-key','test',
 '{"transfer_id":"ingest-1","debit_account_id":"debit","credit_account_id":"credit","amount":"25.0000","currency":"RUB","booking_date":"2026-01-02","value_date":"2026-01-02"}');
DO $$ BEGIN
 IF (SELECT count(*) FROM bank_core.transfer WHERE tenant_id='sql_ingest')<>1 THEN RAISE EXCEPTION 'ingestion replay created a duplicate'; END IF;
END $$;
SELECT bank_core.ingest_transfer_message('sql_ingest','message-error','error-key','test',
 '{"transfer_id":"ingest-error","debit_account_id":"debit","credit_account_id":"credit","amount":"250.0000","currency":"RUB","booking_date":"2026-01-02","value_date":"2026-01-02"}');
DO $$ BEGIN
 IF (SELECT status FROM bank_core.inbound_message WHERE tenant_id='sql_ingest' AND message_id='message-error') IS DISTINCT FROM 'rejected' THEN RAISE EXCEPTION 'ingestion error was not retained'; END IF;
END $$;
DO $$ BEGIN
 BEGIN
  PERFORM bank_core.next_business_date(DATE '2099-01-01');
  RAISE EXCEPTION 'missing calendar unexpectedly resolved';
 EXCEPTION WHEN OTHERS THEN
  IF SQLERRM='missing calendar unexpectedly resolved' THEN RAISE; END IF;
 END;
END $$;
ROLLBACK;
