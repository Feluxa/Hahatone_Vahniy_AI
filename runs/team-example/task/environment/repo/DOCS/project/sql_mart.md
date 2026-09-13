# bank_mart

`bank_mart` is Meridian Clearing's synthetic PostgreSQL warehouse. Files `040` through `059` run after the `bank_core` contract and use only its published account, posting, loan, installment, and FX-rate columns.

The mart stores idempotent tenant-and-date snapshots for account balances, aging, liquidity, FX exposure, reconciliation, monthly turnover, loan performance, cashflow, and customer positions. `refresh_tenant_mart(tenant_id, as_of_date, reporting_currency)` is the standard bounded refresh entry point. It records a reload run, excludes non-`posted` postings, and leaves each amount in its native currency unless an explicit FX rate is used.

`daily_account_balance` is the base fact. A balance begins at zero on `opened_on`; posted signed amounts are accumulated by booking date. A refresh deletes and recreates only the tenant's rows through the explicit as-of date, so rerunning it is idempotent.

`refresh_data_quality` persists contract checks. `refresh_exception_queue` turns reconciliation variance, overdue loans, and negative balances into idempotent operational exceptions. `assert_mart_ready` raises when a requested refresh is incomplete, has error-level quality results, or lacks its requested FX snapshot.

SQL tests live in `tests/sql_mart`. They are intended to run after all lexicographic SQL resources are loaded into an isolated PostgreSQL 16 database, for example:

```sh
psql "$MERIDIAN_DSN" -v ON_ERROR_STOP=1 -f tests/sql_mart/test_daily_balances.sql
psql "$MERIDIAN_DSN" -v ON_ERROR_STOP=1 -f tests/sql_mart/test_loan_and_exceptions.sql
```

Each test opens a transaction, inserts only synthetic fixtures, makes assertions in a `DO` block, and rolls back. Both tests require the project migrations to be applied first.
