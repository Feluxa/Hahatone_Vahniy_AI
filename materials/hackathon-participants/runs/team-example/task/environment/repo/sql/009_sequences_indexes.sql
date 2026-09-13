CREATE INDEX IF NOT EXISTS ix_account_customer ON bank_core.account(tenant_id,customer_id,status);
CREATE INDEX IF NOT EXISTS ix_loan_account ON bank_core.loan(tenant_id,account_id,status);
CREATE INDEX IF NOT EXISTS ix_fx_rate_pair_date ON bank_core.fx_rate(from_currency,to_currency,rate_date DESC);
CREATE INDEX IF NOT EXISTS ix_inbound_message_pending ON bank_core.inbound_message(tenant_id,received_at) WHERE status IN ('received','processing');
CREATE INDEX IF NOT EXISTS ix_transfer_status_date ON bank_core.transfer(tenant_id,status,value_date);
CREATE INDEX IF NOT EXISTS ix_posting_status_date ON bank_core.posting(tenant_id,status,value_date);
ALTER TABLE bank_core.posting ADD CONSTRAINT fk_posting_reversal
 FOREIGN KEY (tenant_id,reversal_of) REFERENCES bank_core.posting(tenant_id,posting_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE bank_core.transfer ADD CONSTRAINT fk_transfer_reversal
 FOREIGN KEY (tenant_id,reversal_of) REFERENCES bank_core.transfer(tenant_id,transfer_id) DEFERRABLE INITIALLY DEFERRED;

