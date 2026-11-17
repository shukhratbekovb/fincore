from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4

from jose import jwt, JWTError
from jose.exceptions import ExpiredSignatureError

from backend.application.auth.errors import AccessTokenExpiredError, InvalidAccessTokenError
from backend.application.auth.interfaces.token_issuer import ITokenIssuer
from backend.infrastructure.settings import Settings


class JWTTokenIssuer(ITokenIssuer):
    def __init__(self, settings: Settings):
        if settings.jwt_secret_key is None:
            raise ValueError("JWT_SECRET_KEY is required for JWTTokenIssuer")
        self._secret_key = settings.jwt_secret_key.get_secret_value()
        self._algorithm = settings.jwt_algorithm
        self._access_token_ttl = timedelta(minutes=settings.jwt_access_token_ttl_minutes)
        self._issuer = settings.jwt_issuer
        self._audience = settings.jwt_audience

    def encode(self, user_id: UUID) -> str:
        if not isinstance(user_id, UUID):
            raise TypeError("User ID must be a UUID")
        now = datetime.now(tz=timezone.utc)
        payload = {
            "sub": str(user_id),
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int((now + self._access_token_ttl).timestamp()),
            "iss": self._issuer,
            "aud": self._audience,
            "jti": str(uuid4()),
            "token_type": "access",
        }
        return jwt.encode(
            payload,
            self._secret_key,
            algorithm=self._algorithm
        )

    def decode(self, token: str) -> UUID:
        if not isinstance(token, str) or not token:
            raise InvalidAccessTokenError()
        try:
            payload = jwt.decode(
                token,
                self._secret_key,
                algorithms=[self._algorithm],
                issuer=self._issuer,
                audience=self._audience,
                options={
                    "require_sub": True,
                    "require_iat": True,
                    "require_nbf": True,
                    "require_exp": True,
                    "require_iss": True,
                    "require_aud": True,
                    "require_jti": True,
                }
            )
            if payload.get("token_type") != "access":
                raise InvalidAccessTokenError()
            if any(type(payload[claim]) is not int for claim in ("iat", "nbf", "exp")):
                raise InvalidAccessTokenError()
            now = int(datetime.now(tz=timezone.utc).timestamp())
            if payload["exp"] <= now:
                raise AccessTokenExpiredError()
            if payload["iat"] > now or payload["exp"] <= payload["iat"]:
                raise InvalidAccessTokenError()
            return UUID(payload["sub"])
        except ExpiredSignatureError:
            raise AccessTokenExpiredError() from None
        except (JWTError, ValueError, TypeError):
            raise InvalidAccessTokenError() from None
