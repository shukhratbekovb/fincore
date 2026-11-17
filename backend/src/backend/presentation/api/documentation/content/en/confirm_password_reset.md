Send only the email `token` in JSON. The server generates the password; client-selected passwords are rejected. Visiting the link with GET does not mutate anything: the frontend reads the fragment, removes it from the URL and sends POST only after explicit user confirmation. Use HTTPS and a page without third-party scripts or analytics.

After transaction commit, success returns `200 {"password": "..."}` with `Cache-Control: no-store`. Display the password once and let the user save it. Do not send the response to logs, analytics or persistent browser storage. If the response is lost, start a new reset: the old token has already been consumed.

All user sessions and remaining reset links are revoked in the same transaction; a notification without the password is queued. Sign in separately through login. Previously issued access JWTs remain valid until expiry. Unknown, expired, consumed, wrong-purpose tokens and ineligible accounts all return `400 invalid_password_reset_token`. The limit is 20 requests per minute per IP; `429` includes `Retry-After`.

Limits use a shared Redis instance. If it is unavailable, the API returns `503 rate_limiter_unavailable` without performing the operation.
