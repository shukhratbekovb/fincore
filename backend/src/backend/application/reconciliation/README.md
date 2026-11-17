# Ledger reconciliation

`ReconcileLedgerQuery` is an operational, read-only query. It has no public HTTP
endpoint and does not repair balances or rewrite immutable journals.

The application depends on `ILedgerReconciliationReader`. The PostgreSQL adapter
owns a separate READ ONLY transaction and performs **one SELECT**, so totals,
findings and examples observe the same MVCC snapshot even while transfers commit.
It is intentionally separate from the write UoW. It takes no row locks.

Checks cover:

- Wallets missing a balance or ledger account; account identity/currency/type/status.
- Missing wallet references and invalid system funding accounts.
- Negative projection values/versions and balance mismatch against credit minus
  debit postings on all wallet accounts, including closed/frozen wallets.
- Journal debit/credit totals and the current two-entry posting contract.
- Entry amount/side, account and journal references, currency, posting timestamp.
- Journal kind, exactly one completed business source, source currency/time.
- Exact source amount and debit/credit wallet or system funding account pairing.
- Exactly one journal for completed transfers/top-ups, none for rejected ones.

Amounts are Python integers; PostgreSQL aggregates BIGINT into NUMERIC. Currencies
are never converted or added together. Version is checked for non-negativity,
not equality with entry count: it is an optimistic concurrency version.

The report includes complete counts and at most `sample_limit` examples **per
finding code** (default 10, allowed 1..100), ordered deterministically by entity
identity. `issue_count` counts failed checks, not unique corrupted entities: one
entity can appear under several findings. Sampling does not limit the scan.
A clean empty ledger is consistent. Missing/inaccessible tables and SQL failures
are execution failures, never a successful empty report.

Run from `backend` with configured DATABASE_URL:

```sh
poetry run python -m backend.bootstrap.reconcile_ledger --sample-limit 10
```

Exit codes: `0` consistent; `1` findings; `2` execution or argument failure.
Stdout contains the JSON report; execution failures produce a sanitized stderr
message without connection parameters. Docker operators can run the same module
inside the API image. Do not expose its output publicly: examples contain IDs
and internal accounting amounts.

Run on demand or via a scheduled job. This scans financial history, so its cost
grows with ledger size; schedule it away from peak load, monitor duration and
use a connection role with SELECT permissions only. Correctness relies on one
statement snapshot, not on privileged access or disabled constraints. Integrity
constraints remain the first line of defense; reconciliation independently
catches projection drift and legacy/import corruption. A clean report is not a
proof against coordinated tampering with every source and accounting record.
