# Verification report — 15 November 2026

This report covers the implemented frontend Docker/IP chain, confirmation resend,
CI configuration and service-data maintenance. It records local checks; it is not
a GitHub Actions run or a production delivery/benchmark report.

## Backend

Environment: macOS, Python 3.14.0, pytest 9.2.0, locked Poetry dependencies.
Dedicated Docker PostgreSQL 17, Redis 8 and Mailpit v1.27.4 were used. Persistence
tests create isolated schemas; neither the development database nor its data was
used by the test suite. Docker runtime uses Python 3.13; the workflow targets 3.13.

```bash
FINCORE_TEST_DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:PORT/fincore_test \
FINCORE_TEST_REDIS_URL=redis://HOST:PORT/0 \
FINCORE_TEST_SMTP_PORT=1025 FINCORE_TEST_MAILPIT_URL=http://HOST:8025 \
poetry run pytest --cov --cov-report=term-missing --cov-report=xml --junitxml=pytest.xml
```

Result: **1841 passed**, **zero skipped**, **98.85% line/branch combined coverage**.
The configured minimum is **91%**. The CI JUnit guard confirmed that every reported
test passed and none was skipped.

New checks cover generic public resend and Redis limits, old-token invalidation,
concurrent resend/confirm, outbox rollback, localized examples, proxy IPv4/IPv6
boundaries, cleanup retention/batches/locks, refresh-chain retention, dry-run,
CLI/scheduler shutdown, permanent replay and the archive/duplicate-post races.
Migration upgrade/downgrade on an empty schema and model parity also pass.

## Frontend and containers

- Prettier, Next route type generation and TypeScript passed.
- **30 Vitest tests passed**; production Next.js build passed.
- Both production Docker images built; production/dev Compose validated.
- A separate temporary Compose project started PostgreSQL, Redis, Mailpit,
  migrations, API, worker, frontend and maintenance on a fresh database.
- Its production API gateway passed register → delivered email → resend → old
  token rejection → new confirmation → login → wallet creation.
- Login returned only the authenticated acknowledgement; cookies had Secure and
  HttpOnly. Invalid proxy authentication, IP lists and foreign Origin were rejected.
- A synthetic trusted ingress address `203.0.113.42` and original User-Agent were
  verified in PostgreSQL. A forged X-Forwarded-For did not replace that address.
- Maintenance `--dry-run` ran successfully inside the runtime container.

The Docker smoke check simulated authenticated TLS ingress using HTTP requests to
the loopback frontend. Actual Nginx/TLS configuration and public DNS were not
changed. This is an API/container integration check, not a new visual browser test.

The development migration was subsequently applied, API port 8017 restarted,
readiness and the new OpenAPI resend route checked, and the frontend's existing
development gateway confirmed reachable.

## CI and remaining external checks

[GitHub Actions](../.github/workflows/ci.yml) provides three jobs: backend with real
dependencies and a 91% gate/no-skips check; frontend formatting/types/tests/build;
and Compose/image/container smoke checks. Reports are uploaded for 14 days.
Workflow YAML and the no-skips script were checked locally. First actual Actions
execution requires pushing these changes to GitHub.

Still external to this verification: production SES delivery, the owner's Nginx
configuration, real HTTPS, VPS deployment and a measured performance benchmark.
