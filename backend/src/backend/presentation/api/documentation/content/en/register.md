Creates a user in `pending_confirmation` state. Username and email are normalized to lowercase.
Both must be unique. No password is accepted or generated at this step.

A one-time confirmation and its delivery task are saved together with the user. The `201` response
contains only `user_id`; it does not return tokens or guarantee email delivery. The separate outbox worker
must be running with SMTP configured. The confirmation lifetime is configurable, with a default of one hour.

```bash
curl -X POST http://127.0.0.1:8000/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","email":"alice@example.com"}'
```

Continue with `POST /v1/auth/confirm` after obtaining the confirmation token through the delivery flow.
Repeating registration for the same username/email returns `409`; it does not resend confirmation.
Use `POST /v1/auth/confirm/resend` with the email address to request a new link. The response is generic; earlier registration links are invalidated only when a new challenge is issued.

Redis limits registration attempts: defaults are 10 requests per hour per IP and 3 per hour per email, including registration conflicts. Email normalization matches the domain. Changing IP does not reset the email budget. Configure REGISTER_RATE_LIMIT_IP_PER_HOUR and REGISTER_RATE_LIMIT_EMAIL_PER_HOUR. A resolvable client IP is required.

Exceeding either budget returns `429` with `Retry-After`. Redis unavailability returns `503 rate_limiter_unavailable` without executing the use case.
