# Docker on one VPS

Run commands from the repository root. Docker Engine and the Docker Compose v2
plugin must be installed. The root Docker environment is separate from
`backend/.env` and the root `compose.dev.yml` for local development dependencies.

## Configure

```bash
cp .env.example .env
chmod 600 .env
```

Edit `.env` before starting:

- Generate independent PostgreSQL and JWT secrets, for example with
  `python3 -c "import secrets; print(secrets.token_hex(32))"`.
- Put the same database password in POSTGRES_PASSWORD and DATABASE_URL.
  DATABASE_URL must use the Compose hostname `postgres`, port 5432. Percent-encode
  reserved URL characters in passwords, or generate a hex password.
- Set `PUBLIC_APP_ORIGIN` to the exact public HTTPS origin, for example
  `https://wallet.example.com`, without a trailing slash or path.
- Generate a separate `FRONTEND_TRUSTED_PROXY_TOKEN` of at least 32 characters.
  It is server-only and must also be configured in your Nginx ingress.
- Configure SES SMTP host, username, password, verified sender and HTTPS frontend
  URLs. SES SMTP credentials are different from AWS API access keys. The worker
  validates this configuration at startup; API readiness does not verify SES.
- Review the HTTP rate budgets, operation amount settings and API_WORKERS. Each
  API process has its own PostgreSQL/Redis pool; multiplying workers increases
  the total number of connections. Start with one worker and measure usage.

The root `compose.yml` builds `backend/Dockerfile` and `frontend/Dockerfile` with
their respective directories as build contexts. Standalone builds:

```bash
docker build -t fincore-backend:local backend
docker build -t fincore-frontend:local frontend
```

No real credentials are included in the image. `backend/.dockerignore` only admits the
backend source, migrations and dependency manifests; local env files, frontend,
tests, Git history and caches are excluded.

## Start

```bash
docker compose config -q
docker compose up -d --build --wait
docker compose ps -a
curl --fail http://127.0.0.1:3000/health
docker compose exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready').read().decode())"
```

Services:

| Service     | Purpose                                                                   |
| ----------- | ------------------------------------------------------------------------- |
| postgres    | PostgreSQL 17, persistent named volume, no published port                 |
| redis       | Shared rate limits, AOF, noeviction, persistent volume, no published port |
| migrate     | One-shot `alembic upgrade head`; must succeed before API/worker start     |
| api         | Uvicorn/FastAPI, internal port 8000, no host port                         |
| frontend    | Next.js standalone on Node 24, `127.0.0.1:FRONTEND_PORT` (default 3000)   |
| worker      | Independent outbox delivery process using SES SMTP                        |
| maintenance | Service-data cleanup immediately on startup and every 24 hours            |
| mailpit     | Optional `dev` profile, local email capture                               |

API, worker, maintenance and migration service use the same multi-stage image. The runtime
contains only main dependencies, runs as UID 10001, has a read-only filesystem
and a temporary `/tmp`. There are no source bind mounts and no development reload.
Docker starts an init process and sends stop signals to the application. API has
40 seconds for graceful shutdown, Docker waits 50; worker has a 60-second grace
period. If you change worker SMTP/send timeouts, adjust the grace period too.

Frontend also runs as a non-root user with a read-only filesystem and temporary
`/tmp`. Its liveness probe is `GET /health`; API readiness covers PostgreSQL/Redis.

`migrate` exiting with code 0 is expected. Long-running services use
`restart: unless-stopped`. Health status `unhealthy` does not by itself restart a
container: inspect logs and fix the dependency. Startup ordering only controls
startup; applications still need to handle dependency outages during operation.

Production Compose creates its own volumes. It does not import existing data from
`compose.dev.yml`. `docker compose down` preserves named volumes;
`down -v` deletes the root stack's PostgreSQL/Redis data.

## Health and request logs

| Endpoint                         | Semantics                                                 |
| -------------------------------- | --------------------------------------------------------- |
| Frontend GET /health             | Next.js process liveness, no API/database queries         |
| API GET /health and /health/live | Process is able to serve HTTP; no dependency queries      |
| API GET /health/ready            | Concurrent PostgreSQL SELECT 1 and Redis PING, 200 or 503 |

Each readiness probe is bounded by HEALTH_CHECK_TIMEOUT, default 2 seconds,
maximum 10. Failure responses contain only component names and ok/unavailable;
no database URL, error text or credentials. SMTP is excluded: API enqueues mail,
and the independent worker delivers it. A 200 readiness response does not prove
that SES delivery works or that a particular business operation will succeed.

The request middleware emits one JSON event per HTTP request with timestamp,
request_id, method, route template, response status and duration_ms. Incoming
request IDs are not trusted: the server generates a new ID and returns it in
X-Request-ID, including generic 500 errors. Unknown paths are logged as unmatched.
Raw paths, query strings, headers, bodies, passwords and tokens are not logged by
the middleware. Tracebacks emitted with exc_info retain exception class and
frame locations without exception text or local values. Do not add application
logs containing auth bodies or credentials.

```bash
docker compose logs --tail=100 -f frontend api worker maintenance
```

The API launcher passes a serializable JSON logging configuration to Uvicorn so
spawned API workers also use it. Standard Uvicorn access logging is disabled to
avoid duplicate raw-URL logs. The worker uses the same formatter. Docker rotates
each container's output at 10 MB, keeping three files. This is request logging;
no metrics collector, dashboard, alerting service or external log system is installed.

## Your reverse proxy

No Nginx configuration is supplied or changed. Configure your ingress to terminate
HTTPS and proxy the frontend to `127.0.0.1:3000` (or `FRONTEND_PORT`). It must:

- **Overwrite** `X-FinCore-Proxy-Token` with the server-side secret matching
  `FRONTEND_TRUSTED_PROXY_TOKEN`; never expose it to browser JavaScript.
- **Overwrite** `X-Real-IP` with the verified single client IPv4/IPv6 address.
  For a direct Internet-facing Nginx this is the peer address. An upstream CDN/LB
  requires its own explicitly trusted real-IP configuration before using this value.
- Preserve the browser's `User-Agent` and normal Origin header.

The Next gateway authenticates ingress metadata before forwarding API requests.
It ignores browser-supplied forwarding chains and sends only the verified single IP.
Production API gateway responses are `503` for missing/invalid server config, `403`
for an invalid proxy token and `400` for an invalid IP. Therefore a direct loopback
visit can render pages but cannot use the API until trusted ingress headers are set.
The configured `PUBLIC_APP_ORIGIN` supplies the expected CSRF origin; spoofed Host or
forwarded-proto headers do not change it.

API trusts forwarding headers only from the frontend's fixed address on the dedicated
internal gateway network. Defaults: `GATEWAY_SUBNET=172.30.85.0/29`,
`FRONTEND_INTERNAL_IP=172.30.85.2`, `API_INTERNAL_IP=172.30.85.3`. Change all three
together if that subnet conflicts. API also joins the separate database network;
frontend does not join it. No backend host port is published.

Host-based development without a proxy token ignores forwarded IP headers and
continues to record the local Next peer. Production cookie handling requires HTTPS.

## Update

```bash
docker compose build
docker compose stop frontend api worker maintenance
docker compose run --rm migrate
docker compose up -d --wait
```

Continue to the last step only if migrations succeed. Stopping application services first
avoids running old code against an incompatible schema during a single-VPS update.
The first `up` also includes the migration job; Alembic already at head is a no-op.
Application rollback is not an automatic database downgrade; schema changes must
be compatible with the application version you intend to run.

Migration `20261115_06` adds cleanup indexes and immutable permanent replay receipts.
After the first receipt is archived, downgrade is refused to avoid losing replay
protection. Use application versions that understand receipts; an older image can
fail requests against these guards. Do not roll back to a receipt-unaware application.
See [maintenance](maintenance.md) for dry runs and retention settings.

## Local email smoke test

For host-based development, use the separate root `compose.dev.yml` instead of
the production stack. Configure `backend/.env` from `backend/.env.example`, then
run from the repository root:

```bash
docker compose --env-file backend/.env -f compose.dev.yml up -d --wait
```

This starts only PostgreSQL (`127.0.0.1:55432`), Redis (`127.0.0.1:56379`) and
Mailpit (SMTP `127.0.0.1:1025`, UI `127.0.0.1:8025`). Run the API and worker
through Poetry on the host. From `backend/`, `make infra`, `make infra-down` and
`make infra-logs` manage the same dev project. Individual `make postgres`,
`make redis`, `make mailpit` commands also use this file.

The dev volume names remain `fincore-database_postgres_data` and
`fincore-rate-limits_redis_data` to retain existing local data. When switching
from the former separate Compose files on another checkout, remove only their
old containers once before starting the new dev project:

```bash
docker stop fincore-postgres fincore-redis
docker rm fincore-postgres fincore-redis
```

These commands retain the data volumes. If an old Mailpit container is still
running, stop and remove it as well to release ports 1025/8025. Do not run both
the dev and production Mailpit profiles on the same UI port.

To capture email from the production stack using a local Mailpit service:

Use a separate local env file or edit the local root `.env`:

```dotenv
SMTP_BACKEND=local
SMTP_HOST=mailpit
SMTP_PORT=1025
SMTP_SECURITY=none
SMTP_USERNAME=
SMTP_PASSWORD=
FRONTEND_CONFIRMATION_URL=https://your-configured-domain.example/confirm
FRONTEND_PASSWORD_RESET_URL=https://your-configured-domain.example/reset-password
```

```bash
docker compose --profile dev up -d --build --wait
```

Mailpit UI is at `http://127.0.0.1:8025`; SMTP is available internally as
`mailpit:1025`. The optional Mailpit service is not a production email provider.
The production gateway still requires the HTTPS origin and authenticated ingress.
For a plain HTTP localhost UI use the host-based development setup above.

## Wallet operations and reconciliation

Owner-only POST `/v1/wallets/{wallet_id}/freeze` and `/unfreeze` return 204 and are
idempotent. Frozen wallets reject new incoming/outgoing money movements while
history and balances remain readable; ledger accounts stay open. Closed wallets
cannot be unfrozen. These operations do not implement administrative freezes.

Run the read-only reconciliation query inside the application container:

```bash
docker compose exec -T api python -m backend.bootstrap.reconcile_ledger --sample-limit 10
```

It checks journal/projection consistency in one database snapshot, prints JSON
with full counts and bounded examples, and never repairs data. Exit status:
0 consistent, 1 findings, 2 execution failure. This is a consistency report,
not a backup or a restore mechanism. Backup configuration is outside this change.
