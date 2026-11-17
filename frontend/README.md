# FinCore frontend

Next.js 16 / React 19 / TypeScript interface connected to the FastAPI backend.
Wallet balances, transfers, history, users and sessions are read from the server.
Only theme preferences and pending monetary request keys are stored in the browser.

## Local development

Node.js 20.19+ and npm; production Docker and CI use Node.js 24.
Python/Poetry and Docker are required for the backend.

From the repository root, prepare `backend/.env` using `backend/.env.example`,
then start dependencies:

```bash
docker compose --env-file backend/.env -f compose.dev.yml up -d --wait
cd backend
poetry install --with test
poetry run alembic upgrade head
# Enable sandbox funding locally; actual permission is granted separately below.
SANDBOX_ENABLED=true make dev
```

In a second terminal, from `backend/`, start the email worker:

```bash
SMTP_BACKEND=local SMTP_HOST=127.0.0.1 SMTP_PORT=1025 SMTP_SECURITY=none \
FRONTEND_CONFIRMATION_URL=http://localhost:3000/confirm \
FRONTEND_PASSWORD_RESET_URL=http://localhost:3000/reset-password make worker
```

In a third terminal:

```bash
cd frontend
npm ci
cp .env.example .env.local
npm run dev
```

Open **http://localhost:3000**. `BACKEND_API_URL` in `.env.local` is server-only and
points to FastAPI, by default `http://127.0.0.1:8000`. Restart Next.js after changing
it. If API runs on another port, e.g. 8017, use that URL. The local session in this
workspace has been configured for port 8017.

To restart the API on that port from `backend/`, use
`SANDBOX_ENABLED=true make dev DEV_PORT=8017`. The existing API on 8000 is separate.

Use the same hostname (`localhost`) when signing in and opening email links;
`localhost` and `127.0.0.1` have different browser cookies.

## Registration and a funded test account

1. Click “Создать аккаунт”, enter a unique login (5+ Latin letters/digits/underscore)
   and an address such as `my_test@example.com`.
2. Open Mailpit at http://127.0.0.1:8025, find your email and follow the confirmation
   link. Set a password containing upper/lowercase letters, a digit and a special
   character. Tokens are read from the URL fragment, immediately removed from the
   address bar and submitted in a request body. If the email is missing or the
   link expired, use “Не пришло письмо подтверждения?” on login, registration or
   confirmation. Enter the email to request a replacement link; the previous
   registration link stops working. The response does not disclose whether an
   account exists, and repeated requests are rate-limited.
3. Sign in and create two wallets in the same currency, for example CAD.
4. Copy your user ID from Profile, then grant **only this local account** funding
   permission from `backend/`:

   ```bash
   PYTHONPATH=src poetry run python -m backend.bootstrap.sandbox --operator-user-id YOUR_USER_UUID
   ```

5. Open a wallet and use “Sandbox-пополнение”. Then try own-wallet transfers,
   history, freeze/unfreeze, rename, and closing an empty wallet.
6. For an external transfer, register another account in a separate browser profile
   and copy its 20-digit wallet number from wallet details. Select “Пользователю”,
   enter the number, check the recipient's username/currency, then confirm the
   transfer. Sessions share cookies across tabs of the same origin.

`SANDBOX_ENABLED=true` must be set on the API process. The UI cannot grant operator
permissions. You can revoke permission using the same CLI with `--revoke`.
All amounts are virtual. Production configuration keeps sandbox disabled by default.

## Connected flows

- Registration, email confirmation/resend, login, automatic refresh, logout.
- Password reset with the backend-generated password shown once; password change
  revokes sessions and returns to login.
- Actual profile and active sessions, including device agent/IP; revoke one/all.
- Wallet creation in backend-supported currencies, balances, copyable numbers, rename,
  freeze/unfreeze, closure of zero-balance wallets, operator sandbox top-up.
- Transfers between own wallets and to a user-supplied wallet number; review and
  actual transfer details, including direct links after reload.
- Currency-separated balance totals. String minor amounts are parsed with BigInt;
  no money calculations use floating point. JPY has zero decimal places, other
  supported currencies use two.
- History uses backend filters and cursor pagination. Search is explicitly limited
  to the loaded records. Wallet history uses the wallet-specific endpoint.

The former sessionStorage demo and synthetic recipient have been removed. Backend
ownership checks, wallet statuses, operation limits and rate limits remain authoritative.

Recipient lookup uses `POST /v1/transfer-recipients/resolve` with
`{"wallet_number":"00001234567890123456"}`. It returns only `wallet_id`, `number`,
`currency`, `owner`; `owner` is the recipient wallet owner's username. Requests
require authentication and an exact 20-digit ASCII string. PostgreSQL looks up the
unique number and joins the owner in one query; inactive wallets/owners are not
returned. Redis budgets default to 30 lookups/user/minute and 100/IP/minute.

The frontend debounces complete numbers and discards aborted/stale responses.
Changing the number invalidates the displayed recipient immediately; incompatible
currencies and the sender wallet cannot proceed. The existing transfer command
uses the resolved UUID internally. Pending retry metadata preserves the number
and username across reloads; backend transfer checks still run at execution time.
Wallet details copy the exact number, including leading zeroes, to the clipboard.
Wallet UUIDs are used internally in API requests and route URLs; wallet details
and transfer review do not display them as wallet requisites.

Confirmation resend uses public `POST /v1/auth/confirm/resend` with `{"email":"user@example.com"}`.
It returns a generic 202 response for pending, active and missing accounts. Only
pending accounts receive a new registration challenge. Default Redis budgets are
20 requests/IP/hour and 3 requests/email/hour.

## Session and request handling

`src/app/api/backend/[...path]/route.ts` forwards a fixed allowlist of routes to
FastAPI. Login/refresh tokens are kept in HttpOnly/SameSite=Lax session cookies;
production adds Secure and requires HTTPS. They are never returned to client JS
or stored in localStorage/sessionStorage. Browser requests use the same origin,
so no permissive backend CORS configuration is needed. Logout, password change,
password reset and revocation of all sessions clear cookies.

Mutating routes reject a foreign Origin/cross-site request. Incoming browser
Authorization, cookies and forwarding headers are not passed through verbatim;
only the required token, user agent, content type and idempotency key are forwarded.
In production, the separately authenticated ingress address is also forwarded as
described below.
API responses are not cached. Transport failures produce a generic 502.

Refresh uses a single promise per tab and Web Locks across tabs (when available),
with a fresh auth check before rotating. Failed/expired sessions return to login.
Money request retries retain their idempotency key and payload in sessionStorage,
including across reloads; this is a pending request, never a local balance. A
confirmed success clears the pending request. Keep retrying an uncertain request
with its saved key to determine its outcome. Maintenance compacts old backend
idempotency records into permanent replay receipts; cleanup does not allow the
same actor/scope/key to execute a second transfer. A different payload with that
key remains a conflict. There is no client-side expiry that silently replaces an
uncertain request with a new key.

In this local Next.js → API topology, the backend records the Next.js server peer
IP (127.0.0.1), and IP budgets are shared. Browser-supplied X-Forwarded-For is not
trusted. Device user-agent is forwarded. Deployment behind a reverse proxy needs
a trusted forwarding chain. Local development needs no proxy token or production
origin configuration.

## Production Docker and client IP

Follow the repository [VPS deployment guide](../docs/deployment.md). The root
`compose.yml` builds `frontend/Dockerfile` as a Next.js standalone image, runs it
as a non-root user with a read-only filesystem, and publishes only
`127.0.0.1:${FRONTEND_PORT:-3000}` for the frontend. `/health` is a liveness endpoint;
the API healthcheck separately verifies PostgreSQL and Redis. The backend API is
available only on Docker networks, without a host port.

Set these **server-only** runtime variables in the root `.env`, not a `NEXT_PUBLIC_`
variable or browser configuration:

```dotenv
PUBLIC_APP_ORIGIN=https://wallet.example.com
FRONTEND_TRUSTED_PROXY_TOKEN=replace-with-an-independent-random-secret
```

Generate the proxy token independently of JWT and database secrets, for example
with `python3 -c "import secrets; print(secrets.token_hex(32))"`. The token must
contain at least 32 characters. `PUBLIC_APP_ORIGIN` must be the exact HTTPS origin
without a path or trailing slash; it is used for mutation Origin checks.

Nginx configuration is owned by the project owner. Its forwarding contract is:

- Proxy frontend traffic to `http://127.0.0.1:3000` (or `FRONTEND_PORT`).
- **Overwrite** `X-FinCore-Proxy-Token` with the configured secret.
- **Overwrite** `X-Real-IP` with the verified client IP, as one IPv4/IPv6 address.
- Preserve the client User-Agent. Never use a browser-supplied forwarded chain as
  the verified client address. If a load balancer/CDN is later added, configure
  Nginx's trust in that upstream before deriving the client IP.

The gateway validates the ingress token, rejects invalid/multiple IP addresses,
ignores incoming `X-Forwarded-For`, and sends only its verified address to the API.
The secret is not sent to the API or exposed to client JavaScript. Production API
routes return 503 for missing configuration, 403 for an untrusted ingress, and 400
for an invalid client IP; they do not fall back to a shared server address.
Nginx must satisfy this contract before production sign-in works.

The dedicated internal gateway network defaults to `172.30.85.0/29`, frontend
`172.30.85.2`, API `172.30.85.3`. Uvicorn trusts forwarded headers only from that
frontend address. If the subnet conflicts with your VPS networks, change
`GATEWAY_SUBNET`, `FRONTEND_INTERNAL_IP` and `API_INTERNAL_IP` together in the root
environment. No wildcard proxy trust is used.

## Checks

```bash
npm run typecheck
npm test
npm run build
npm run format:check
# Start the real API (SANDBOX_ENABLED=true), worker, Mailpit and Next.js first:
npm run test:e2e
```

Vitest checks exact money/schema handling, the authenticated gateway and production
proxy authentication/IP spoofing boundaries. Playwright
uses installed Chrome and the running local stack (localhost:3000, Mailpit:8025).
It creates synthetic accounts and wallets in the configured development database,
grants its account sandbox permission through the backend CLI, and exercises
registration/email, transfer replay after a lost response and reload, wallet actions,
cursor pagination, cross-tab refresh, responsive layouts, password/reset and sessions.
It leaves synthetic test data in the local DB; use a separate local database if you
want isolation. Keep test databases/rate limits separate from production.

Screenshots are written under ignored `test-results/`. No password is printed or
persisted by the test. This suite verifies integration; backend persistence tests
cover transaction/concurrency invariants separately.

## Continuous integration

[GitHub Actions](../.github/workflows/ci.yml) checks formatting, generated route
types, TypeScript, unit tests with a no-skips JUnit gate and the production build.
Its E2E job provisions fresh PostgreSQL/Redis/Mailpit, migrates the database and
starts the API, email worker and development frontend. CI installs Playwright
Chromium; local runs continue using installed Chrome. All six browser journeys
run with one worker, no automatic retries and forbidOnly enabled.

Reports, failure screenshots/traces and process logs are retained for 14 days.
Another job builds and checks the complete production Compose stack, including
trusted proxy IP and secure cookie behavior. See the [CI guide](../docs/ci.md).
