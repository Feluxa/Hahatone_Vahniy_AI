ALTER TABLE bank_core.tenant DISABLE ROW LEVEL SECURITY;
ALTER TABLE bank_core.customer DISABLE ROW LEVEL SECURITY;
ALTER TABLE bank_core.account DISABLE ROW LEVEL SECURITY;
ALTER TABLE bank_core.posting DISABLE ROW LEVEL SECURITY;
ALTER TABLE bank_core.transfer DISABLE ROW LEVEL SECURITY;
ALTER TABLE bank_core.loan DISABLE ROW LEVEL SECURITY;
ALTER TABLE bank_core.installment DISABLE ROW LEVEL SECURITY;
CREATE OR REPLACE FUNCTION bank_core.current_tenant_id() RETURNS text
LANGUAGE sql STABLE AS $$ SELECT NULLIF(current_setting('bank_core.tenant_id', true),'') $$;
COMMENT ON FUNCTION bank_core.current_tenant_id() IS 'Trusted backend diagnostic setting; it is not an RLS authorization boundary.';
