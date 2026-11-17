Request a new registration confirmation email with `POST /v1/auth/confirm/resend`.
The public endpoint accepts only `email`; no Bearer token or password is required.
The email is normalized using the same rules as registration.

The response is always `202` for a valid admitted request, including unknown addresses
and accounts that are already active or otherwise ineligible. Its message does not
reveal whether the address is registered. This acknowledges the request, not delivery.

Only a user in `pending_confirmation` receives a new challenge. Under the user lock,
all unused registration challenges are invalidated, a new token hash is saved, and an
outbox message is added in one transaction. Previous registration links stop working.
Password-reset challenges are unaffected. The expiry uses
`VERIFICATION_CONFIRMATION_TTL` (default one hour); the outbox worker must be running.

```json
{"email":"alice@example.com"}
```

Redis limits apply before the use case: by default 20 attempts per IP per hour and
3 per normalized email per hour. The budgets also apply to unknown/active addresses.
`429` includes `Retry-After`; `503 rate_limiter_unavailable` prevents execution when
Redis is unavailable. Missing client IP returns `400`; invalid or extra fields return
`422`. A valid request has a small minimum response delay to reduce timing differences.

After receiving the latest email, submit its token and your chosen password through
`POST /v1/auth/confirm`. Repeating `/register` still returns a uniqueness conflict.
