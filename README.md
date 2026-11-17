# FinCore

FinCore is an educational digital wallet platform for virtual CAD transfers. It is a backend-first portfolio project demonstrating transactional consistency, double-entry accounting, concurrency control and idempotent money operations. No real money, banks or payment providers are involved.

## Project status

Implementation update: 17 November 2026.

Documentation baseline: 15 October 2026, based on **FinCore PRD MVP v1.0**, dated 14 October 2026. Requirements and proposed designs below are not claims of implemented functionality.

The backend implements authentication, sessions, wallets, sandbox funding, transfers,
ledger/history/balance queries, Redis request limits, owner freeze/unfreeze and
read-only reconciliation. Root Docker Compose runs frontend, API, email worker,
maintenance, PostgreSQL, Redis and migrations; see [VPS deployment](docs/deployment.md). The Next.js frontend
in `frontend/` is connected to the API through a server-side gateway with HttpOnly
session cookies; see [local integration setup](frontend/README.md).
GitHub Actions configuration checks backend coverage, frontend and container builds.
An actual VPS deployment and SES delivery on a production domain remain to be verified.

## MVP

The [approved scope update of 16 October 2026](docs/scope-update-2026-10-16.md) supersedes the original single-wallet restriction and adds five-section navigation and a profile. Backend implementation details are documented in backend/README.md.

- Email confirmation registration, confirmation resend, login, rotating refresh sessions and logout.
- Multiple named CAD wallets per user, displayed as cards, with transfers between distinct wallets including the user’s own wallets.
- Operator-authorized sandbox funding and synchronous P2P transfers.
- Immutable double-entry ledger with an atomic balance projection.
- Idempotent money-changing requests and cursor-paginated history.
- Owner/participant authorization and audit trails.

Cards, real payments, FX, fees, refunds, holds, recurring transfers, KYC, analytics/export and a public admin panel are outside MVP.

## Stack

Backend: Python 3.13+, FastAPI, Pydantic, SQLAlchemy, asyncpg, Alembic, Uvicorn and
redis-py, managed with Poetry. PostgreSQL stores financial data; Redis enforces
request limits. Frontend: Next.js App Router, React, TypeScript, Tailwind CSS,
Lucide, next-themes and Zod. See the [frontend README](frontend/README.md).

## Run the connected frontend

```bash
cd frontend
npm ci
cp .env.example .env.local
npm run dev
```

Open http://localhost:3000 after starting the backend and email worker. Register,
confirm your email through local Mailpit, and sign in. Wallets, transfers, history,
sessions and passwords use the real API. See [frontend documentation](frontend/README.md)
for connection settings, sandbox operator permissions and end-to-end checks.

## Run the backend locally

Prerequisites: Python compatible with `backend/pyproject.toml` and Poetry installed.

```bash
cd backend
poetry install
cp .env.example .env
# Configure credentials, then start PostgreSQL/Redis and apply migrations.
make infra
poetry run alembic upgrade head
poetry run uvicorn backend.main:app --app-dir src --reload
```

API prefix is `/v1`. `/health` and `/health/live` check process liveness;
`/health/ready` checks PostgreSQL and Redis. RU/EN documentation and full local
setup are described in [backend/README.md](backend/README.md). Run the outbox worker
separately to deliver registration/reset emails.

## Docker on a VPS

From the repository root, copy `.env.example` to `.env`, configure database/JWT
secrets and SES SMTP, then run:

```bash
docker compose up -d --build --wait
```

Frontend is bound to `127.0.0.1:3000`; API, PostgreSQL and Redis have no published ports.
Set the public HTTPS origin and independent proxy secret, then configure your reverse
proxy to overwrite the required ingress headers. Migrations complete before application
services start. See [deployment instructions](docs/deployment.md)
for health checks, logs, updates and optional local Mailpit. Nginx is configured
by the project owner separately; backups and monitoring services are not provisioned.

## Documentation

Start with the [documentation index](docs/README.md).

- [Architecture](docs/architecture.md) and [data model / ERD](docs/data-model.md)
- [Target API contract and errors](docs/api.md)
- [Financial invariants](docs/invariants.md) and [acceptance plan](docs/test-plan.md)
- [Frontend specification](docs/frontend-spec.md)
- [Open decisions](docs/decisions.md) and [delivery plan](docs/delivery-plan.md)
- [ADR-001: Ledger](docs/adr/ADR-001-ledger.md)
- [ADR-002: Idempotency](docs/adr/ADR-002-idempotency.md)

## Planned demo

Seed synthetic Alice and Bob users and a separate sandbox operator. The operator credits Alice with CAD 500.00; Alice transfers CAD 100.00 to Bob. Expected balances: Alice CAD 400.00, Bob CAD 100.00. Retrying the same transfer request with the same idempotency key must return the original result without another debit. See the [test plan](docs/test-plan.md) for rejection, timeout and concurrency scenarios.

## Release requirements

The [CI workflow](.github/workflows/ci.yml) runs on pushes, pull requests and manual
dispatch. It enforces 91% backend line/branch coverage on Python 3.13/3.14 with real
PostgreSQL, Redis and Mailpit, rejects skipped tests, checks the frontend, runs browser
journeys and verifies the full production Docker stack. See [CI details](docs/ci.md)
and the [17 November verification report](docs/test-report-2026-11-17.md).
Reports are retained for 14 days. Configure branch protection separately to require
**CI required checks** before merging. No deployment or publication is automatic.

Service-data cleanup runs immediately on maintenance container startup and then daily.
It retains full idempotency rows for at least seven days and preserves compact permanent
replay receipts so old pending money requests cannot execute twice. See
[maintenance](docs/maintenance.md) for policy, dry runs and rollback constraints.

Financial acceptance tests must pass against real PostgreSQL, including rollback, reconciliation and concurrent spending tests. Publish reproducible setup, synthetic seed data, CI results and a test report. Frontend checks must cover expired sessions, authorization boundaries, exact money input and safe retries. See [delivery gates](docs/delivery-plan.md).
