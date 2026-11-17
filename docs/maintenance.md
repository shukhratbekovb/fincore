# Service-data maintenance

Implemented 15 November 2026. Maintenance cleans PostgreSQL service tables in short
transactions. Financial transfers, top-ups, ledger accounts, balances, journals and
entries are never deleted by this task. Users awaiting confirmation are retained.

## Policy

| Setting                            | Default | Eligibility                                                                |
| ---------------------------------- | ------: | -------------------------------------------------------------------------- |
| CLEANUP_SESSION_RETENTION_DAYS     |       7 | Session expired or was revoked at least this many days ago                 |
| CLEANUP_CHALLENGE_RETENTION_DAYS   |       7 | Challenge expires_at is at least this many days in the past                |
| CLEANUP_OUTBOX_RETENTION_DAYS      |      30 | Terminal sent/failed/expired message completed at least this many days ago |
| CLEANUP_IDEMPOTENCY_RETENTION_DAYS |       7 | Full record is this old and expires_at has passed                          |
| CLEANUP_BATCH_SIZE                 |     500 | Parent rows per transaction; 1–1000                                        |
| CLEANUP_MAX_BATCHES                |      20 | Maximum batches per table per invocation; 1–1000                           |
| CLEANUP_INTERVAL_SECONDS           |   86400 | Loop interval after a run finishes; 60–2592000                             |

Retention settings accept 1–36500 days. Cleanup uses PostgreSQL time so an application
host's clock cannot bypass the database's minimum 24-hour idempotency protection.
Terminal cutoffs are inclusive (`<=`). Challenge cleanup retains recently expired
and used links through their original expiry plus retention period.

Active sessions and their complete rotated refresh-token chains remain available
for reuse detection. For an eligible session, all its refresh tokens are deleted
in one statement, then the session, in the same transaction. Rows locked by live
operations are skipped with `FOR UPDATE SKIP LOCKED`. Pending/processing outbox
messages remain under the delivery worker's control; it already clears secret
payloads on terminal states.

## Permanent monetary replay receipts

Before deleting a full idempotency record, maintenance inserts a compact immutable
receipt in the same transaction. It stores:

- SHA-256 digest of the actor/scope/key identity, without the raw client key;
- original payload hash and financial resource UUID;
- archive timestamp.

Receipts are permanent and grow with completed financial operations. This is an
intentional correctness record, not a TTL cache. The financial operation itself
also remains permanent. A late retry with the same actor/scope/key returns the
original result; a different payload still returns `409 idempotency_conflict`.
Frontend pending commands keep their existing keys after reload, with no retry-age
cutoff and no need to manufacture a new key to recover an uncertain result.

The repository checks receipts after its INSERT/conflict wait, covering cleanup
committing while a retry waits. Database triggers require a matching receipt before
deleting an expired full record, prevent receipt updates/deletes/truncate, and
reject a completed replay reservation that changes a previously archived result.

Migration `20261115_06` must be applied before running this code. Downgrade acquires
table locks and refuses once any receipt exists. Deploy receipt-aware application
versions after archival; rolling back only the image to older code is unsupported.

## Run and preview

From `backend/` with the normal database environment:

```bash
make cleanup-preview
make cleanup
PYTHONPATH=src poetry run python -m backend.bootstrap.cleanup --batch-size 100 --max-batches 5
```

Production Compose runs the `maintenance` service immediately on startup and then
daily. It handles SIGTERM and finishes the current run before exiting. Failures log
only their exception class and are retried at the next interval. Re-running is safe.

To inspect candidates without modifying data inside an existing production stack:

```bash
docker compose run --rm --no-deps maintenance python -m backend.bootstrap.cleanup --dry-run
docker compose logs --tail=100 maintenance
```

`--dry-run` counts all eligible rows in one statement snapshot, without writes or
row locks; batch limits apply only to actual deletion. JSON reports contain the
database cutoff time, dry_run flag, counts per table, receipts_created and
batch_limit_reached. Preview counts are candidates, not deletions; receipts_created
is zero. Actual counts describe committed batches. If a run fails midway, earlier
batches remain committed and a later run handles remaining rows.

Exit codes: 0 for a successful one-shot run, 2 for configuration/database failure.
When batch_limit_reached is true, more work may remain; re-run or adjust the bounds.
Another worker's locks can also leave candidates for the next scheduled run.
No passwords, token hashes, email addresses, IPs or raw keys appear in the report.

The same CLI can be scheduled by host cron instead of the Compose loop: disable
the maintenance service to avoid redundant schedulers. No Celery or broker is needed.
