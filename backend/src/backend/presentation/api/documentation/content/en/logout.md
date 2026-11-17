Revokes the session associated with the supplied refresh token. An older rotated token can also
identify its session for sign-out. No access-token header is required.

```bash
curl -X POST http://127.0.0.1:8000/v1/auth/logout \
  -H 'Content-Type: application/json' \
  -d '{"refresh_token":"example-refresh-token"}'
```

The response is always `204` with no body for a well-formed request, including an unknown token,
a missing session or an already revoked session. Repeating the request is safe. Malformed input returns `422`.
Only the associated session is revoked; other sign-ins remain active.

Further refreshes of this session are rejected. Already issued access JWTs are not automatically
invalidated by this operation; immediate access revocation requires a session-state check in protected endpoints.
After a successful response, discard both locally stored tokens.
