Exchanges the current refresh token for a new access token and a replacement refresh token.
The original session ID and absolute expiry are preserved; refreshing does not extend the session.
The latest IP and optional User-Agent are recorded while the original sign-in metadata is retained.

```bash
curl -X POST http://127.0.0.1:8000/v1/auth/refresh \
  -H 'Content-Type: application/json' \
  -H 'User-Agent: FinCoreDocs/1.0' \
  -d '{"refresh_token":"example-refresh-token"}'
```

After `200`, replace both stored tokens with the returned values. The consumed refresh token must
never be used for another refresh. If it is reused while the session is valid, the server revokes
the session and returns `401 invalid_refresh_token`. Unknown, expired and revoked tokens/sessions
also return that same code. Inactive accounts return `403 user_inactive`.

**Allow only one refresh request at a time per session.** A concurrent request or an automatic retry
after an ambiguous network failure can be detected as reuse and revoke the session. The endpoint has
no idempotency key or retry grace period. Sign in again when a valid current refresh token is unavailable.
