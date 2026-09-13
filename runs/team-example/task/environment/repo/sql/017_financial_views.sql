CREATE OR REPLACE VIEW bank_core.daily_account_movement AS
SELECT tenant_id,account_id,currency,value_date,
 SUM(amount) FILTER (WHERE status='posted')::numeric(20,4) AS net_movement,
 COUNT(*) FILTER (WHERE status='posted') AS posted_count
FROM bank_core.posting GROUP BY tenant_id,account_id,currency,value_date;
CREATE OR REPLACE VIEW bank_core.transfer_summary AS
SELECT tenant_id,status,currency,value_date,COUNT(*) AS transfer_count,SUM(amount)::numeric(20,4) AS transfer_amount
FROM bank_core.transfer GROUP BY tenant_id,status,currency,value_date;
CREATE OR REPLACE VIEW bank_core.overdue_installment AS
SELECT i.tenant_id,i.loan_id,i.installment_no,i.due_date,
 (i.principal_due+i.interest_due-i.paid_amount)::numeric(20,4) AS unpaid_amount
FROM bank_core.installment i WHERE i.due_date<CURRENT_DATE AND i.paid_amount<i.principal_due+i.interest_due AND i.status<>'waived';

