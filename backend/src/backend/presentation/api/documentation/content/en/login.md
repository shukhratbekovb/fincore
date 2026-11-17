Checks the credentials and creates a separate session for each successful sign-in.
Returns an access JWT and an opaque refresh token in JSON. No authentication cookies are set.

The existing password is checked unchanged, with a length limit of 1–256 characters. The current
new-password complexity policy is not applied here, allowing accounts with older passwords to sign in.
Unknown usernames, absent account passwords and incorrect passwords all return `401 invalid_credentials`.
An inactive account returns `403 user_inactive` after a correct password has been verified.

```bash
curl -X POST http://127.0.0.1:8000/v1/auth/login \
  -H 'Content-Type: application/json' \
  -H 'User-Agent: FinCoreDocs/1.0' \
  -d '{"username":"alice","password":"ExamplePassword1!"}'
```

Client IP and optional User-Agent are recorded as session metadata. They are determined from the
connection/trusted proxy and the header, not JSON fields. Different sign-ins create different sessions.
The default access-token lifetime is 30 minutes, and the default session lifetime is 30 days;
deployment settings can change both. Store the returned refresh token for subsequent refresh/logout calls.

Redis limits all sign-in attempts, including successes and invalid credentials: defaults are 30 requests per minute per IP and 10 per normalized username, whether or not the account exists. Changing IP does not reset the username budget; case changes share a budget. Configure LOGIN_RATE_LIMIT_IP_PER_MINUTE and LOGIN_RATE_LIMIT_USERNAME_PER_MINUTE. This is a temporary window, not a permanent account lock.

Exceeding either budget returns `429` with `Retry-After`. Redis unavailability returns `503 rate_limiter_unavailable` without executing the use case.
