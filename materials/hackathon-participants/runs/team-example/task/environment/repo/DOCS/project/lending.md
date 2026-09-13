# Lending component

The lending component is a fully synthetic, in-process reference implementation for a fixed-rate amortizing loan book. It has no dependency on payments or on an external database. All identifiers and policy values in tests are invented examples.

`LoanService.open()` is the demonstration entrypoint for loan origination. It stages a `Loan` and its complete schedule through the injected `IUnitOfWork` and commits them as one memory-adapter transaction. `PaymentAllocationService.allocate()` accepts a supplied payment reference and allocates it in this order: overdue interest, overdue principal, current interest, current principal, then a tenant-and-loan-scoped early-funds balance. The service rejects duplicate payment references within the same loan. Early funds remain unapplied until a separate application operation consumes them; that operation is intentionally not implemented here.

`DelinquencyService.assess()` calculates days past due from unpaid installments and an explicit `CreditPolicy`; its optional persistence flag writes status changes through the UoW. `RestructuringPreviewService.preview()` is read-only and returns eligibility, reasons, proposed maturity, and a payment estimate. `PortfolioQueryService` returns tenant-scoped summaries and rows.

`lending_providers()` is the Dishka composition entrypoint. It returns `LendingStoreProvider` for the application-scoped single-process store and read repository, then `LendingRequestProvider` for the request-scoped UoW and stateless application services. Compose it with `make_async_container(*lending_providers())` and resolve services inside `async with container()` request scopes. Production adapters can replace the bindings while retaining the application and domain contracts. The memory adapter is intended for demos and tests only.

Run the focused suite from `meridian/`:

```shell
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend/src .venv/bin/python -m pytest tests/lending -q
```
