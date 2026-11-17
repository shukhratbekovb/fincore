FinCore API documents the currently implemented authentication endpoints and application health check.
Use the **RU / EN** links above to switch documentation language. Paths, JSON field names,
operation identifiers and error codes are identical in both versions. Actual API error messages remain English.

## Quick start

1. `POST /v1/auth/register` with a username and email. Save the returned `user_id`.
2. Obtain the registration confirmation token through the delivery flow.
3. `POST /v1/auth/confirm` with that token and a new password. A successful response is `204` without a body.
4. `POST /v1/auth/login` with the username and password to receive an access/refresh token pair.
5. Use `POST /v1/auth/refresh` to rotate the refresh token. Store the replacement after every successful refresh.
6. `POST /v1/auth/logout` with a refresh token to revoke its session.

Registration creates a pending account and queues a confirmation delivery task. A separate outbox worker delivers messages through local Mailpit SMTP or production SES SMTP.
`201` confirms that the task was saved, not that an email has been delivered. The registration response does
not expose the token. Login is available after confirmation has set the password and activated the account.
Password change is available at `/v1/auth/change-password`, and reset at `/v1/auth/password-reset/request` and `/v1/auth/password-reset/confirm`.

## Requests and examples

The authentication endpoints accept JSON with `Content-Type: application/json`.
`change-password` requires `Authorization: Bearer <access_token>`. Other endpoints require no access JWT; confirmation and refresh/logout use their respective token in the body.
Successful bodies and expected errors are JSON; `204` responses have no body.
Local examples use `http://127.0.0.1:8000`; use your HTTPS API origin in deployed clients.
All accounts, UUIDs and token strings shown here are fictional. **Example tokens are placeholders, not valid JWTs or secrets.**

Reset confirmation forbids unknown JSON fields; other requests currently ignore them. Supplying `ip_address` or `user_agent` in JSON does not set
session metadata. The server uses the connection IP and the optional `User-Agent` header for login/refresh.
User-Agent is client-controlled descriptive information. Behind Nginx, forwarding headers must be
accepted only from the configured trusted proxy. A direct client cannot choose its recorded IP using these headers.

## Tokens and expiry

An access token is a signed JWT. A refresh token is an opaque session secret, and a confirmation token
is a separate one-time registration secret. They are not interchangeable. Tokens are returned in JSON;
the current endpoints do not set authentication cookies.

Configured lifetimes may differ between deployments. Defaults are **30 minutes** for an access token,
**30 days** for a session and **1 hour** for registration confirmation. A token/session is expired at its
expiry instant, not only after it. Refresh preserves the original session ID and absolute expiry.

Serialize refresh requests for each session. Reusing a refresh token that has already been consumed
revokes that session and returns `401 invalid_refresh_token`. Parallel requests may therefore revoke
the session after one request succeeds. After a timeout, blindly retrying the same token is unsafe;
the server might already have consumed it. Obtain a new session by signing in if the outcome is uncertain.

Logout prevents further refreshes for the session. It does **not** automatically invalidate previously
issued access JWTs: immediate access revocation would require a separate session check in protected endpoints.

## Errors

Expected errors use a stable envelope:

```json
{
  "detail": {
    "code": "invalid_credentials",
    "message": "Invalid username or password",
    "errors": []
  }
}
```

Handle `detail.code` and the HTTP status programmatically. `errors` describes validation issues with
`loc`, `message` and `type`; original request values and validation context are not reflected.
Unexpected server failures remain `500` and currently use the framework's plain-text server-error response.
They are not validation failures and do not use the JSON error schema.

| Code | HTTP | Meaning |
| --- | --- | --- |
| `request_validation_error` | 422 | Invalid JSON, missing fields, wrong types, lengths or formats |
| `invalid_username`, `invalid_email`, `invalid_password` | 422 | A domain value failed validation |
| `email_already_exists`, `username_already_exists` | 409 | Registration conflicts with an existing account |
| `invalid_credentials` | 401 | Credentials do not match, or the account has no password yet |
| `user_inactive` | 403 | Account is inactive; login checks this after verifying the password |
| `invalid_refresh_token` | 401 | Unknown, expired, revoked or reused refresh/session |
| `invalid_confirmation_token` | 400 | Unknown token or wrong verification purpose |
| `confirmation_token_expired` | 400 | Confirmation lifetime has elapsed |
| `confirmation_token_used` | 400 | Confirmation has already been consumed |
| `user_not_pending_confirmation` | 409 | Account is no longer awaiting confirmation |
| `user_not_found` | 404 | The user associated with the confirmation is missing |
| `http_error` | Depends on status | HTTP error, including unavailable client IP (`400`) |

The shared handlers also recognize `invalid_access_token` and `access_token_expired` (`401`).
These codes are used by protected change-password. Password reset uses `400 invalid_password_reset_token` for all invalid reset tokens. Reset limits return `429 http_error` with `Retry-After`. The new password is returned once as JSON and is never emailed. All auth responses use `Cache-Control: no-store`.

## Profile and sessions

All `/v1/users/me` operations require `Authorization: Bearer <access_token>`. GET `/v1/users/me` returns your profile, and GET `/v1/users/me/sessions` lists your active sessions. DELETE `/v1/users/me/sessions` revokes all your sessions, while DELETE `/v1/users/me/sessions/{session_id}` revokes one of your own. user_id always comes from the JWT. Profile and IP metadata are not cached. Missing sessions and sessions belonging to another user both return `404 session_not_found`. Revocation prevents refresh; previously issued access JWTs remain valid until expiry.

## Wallets

Active users can POST `/v1/wallets` (creation, `201`), PATCH `/v1/wallets/{wallet_id}` (rename, `204`) and POST `/v1/wallets/{wallet_id}/close` (closure, `204`). A Bearer access JWT is required. The JWT identifies the owner; names contain 1–64 characters after trimming, and currency defaults to USD. Foreign wallets return `404 wallet_not_found`. Nonzero balances prevent closure with `409 wallet_balance_not_zero`; renaming closed wallets returns `409 wallet_closed`. The controlled accounting-state error returns JSON `500 wallet_accounting_state_error`; other unexpected errors may still return a plain-text 500. Read wallets through GET /v1/wallets and GET /v1/wallets/{wallet_id}; history and financial operations are also available.


Financial routes: POST/GET /v1/transfers, GET /v1/transfers/{transfer_id}, POST /v1/sandbox/top-ups, GET /v1/wallets/{wallet_id}/balance and /transactions, GET /v1/users/me/balances and /transactions. Sandbox defaults off and requires a server-managed operator. New monetary responses use minor-unit strings; legacy WalletResponse retains numeric balance_minor.
