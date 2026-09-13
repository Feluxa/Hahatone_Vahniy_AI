# SQL core

SQL resources 001 through 039 create the PostgreSQL 16 bank_core operational model and run in lexical order. 090_core_seed.sql creates bounded synthetic fixtures for tenant_demo and account_demo.

The warehouse boundary is account, posting, loan, installment, and fx_rate with the contract columns. Posting is signed; posted entries contribute to account_balance. Reversals add signed records and do not erase originals.

Write functions provide idempotent posting, transfer, reversal, loan scheduling, allocation, and balance audits. SQL tests use independent BEGIN and ROLLBACK fixtures.

The schema is backend-only: migrations revoke all PUBLIC access. Tenant filtering is an application and trusted-backend responsibility, not an RLS authorization claim; consumers must scope every query and command by tenant_id.
