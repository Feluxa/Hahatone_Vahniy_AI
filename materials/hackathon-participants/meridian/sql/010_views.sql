CREATE OR REPLACE VIEW bank_core.account_balance AS
SELECT a.tenant_id,a.account_id,a.customer_id,a.currency,a.status,
 COALESCE(SUM(p.amount) FILTER (WHERE p.status='posted'),0)::numeric(20,4) AS booked_balance,
 MAX(p.value_date) FILTER (WHERE p.status='posted') AS last_value_date
FROM bank_core.account a LEFT JOIN bank_core.posting p
 ON p.tenant_id=a.tenant_id AND p.account_id=a.account_id AND p.currency=a.currency
GROUP BY a.tenant_id,a.account_id,a.customer_id,a.currency,a.status;
CREATE OR REPLACE VIEW bank_core.loan_position AS
SELECT l.tenant_id,l.loan_id,l.customer_id,l.account_id,l.principal,l.status,
 COALESCE(SUM(i.principal_due+i.interest_due),0)::numeric(20,4) AS scheduled_due,
 COALESCE(SUM(i.paid_amount),0)::numeric(20,4) AS paid_amount,
 (COALESCE(SUM(i.principal_due+i.interest_due),0)-COALESCE(SUM(i.paid_amount),0))::numeric(20,4) AS outstanding_due
FROM bank_core.loan l LEFT JOIN bank_core.installment i ON i.tenant_id=l.tenant_id AND i.loan_id=l.loan_id
GROUP BY l.tenant_id,l.loan_id,l.customer_id,l.account_id,l.principal,l.status;

