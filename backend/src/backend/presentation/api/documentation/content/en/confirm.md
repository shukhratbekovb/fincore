Consumes a registration confirmation token, sets the chosen password and activates the account.
The token and password belong in the JSON body. Opening a link with a GET request does not confirm the account.

The password must be 8–256 characters and contain a lowercase letter, an uppercase letter, a digit
and an ASCII punctuation character, for example `!`, `_` or `-`. Password spaces are not trimmed.
Success is `204` with an empty body; sign in separately to obtain session tokens.

```bash
curl -X POST http://127.0.0.1:8000/v1/auth/confirm \
  -H 'Content-Type: application/json' \
  -d '{"token":"example-confirmation-token","password":"ExamplePassword1!"}'
```

Replace the example token with the real registration token. Invalid or wrong-purpose tokens return
`400 invalid_confirmation_token`; expiry returns `400 confirmation_token_expired`; reuse returns
`400 confirmation_token_used`. A rejected new password returns `422` without consuming the confirmation.
If the account is no longer awaiting confirmation, the response is `409`; a missing user produces `404`.
This endpoint is for registration only, not password resets or payments.
