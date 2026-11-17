from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from jose import jwt
from pydantic import ValidationError

from backend.application.auth.errors import AccessTokenExpiredError, InvalidAccessTokenError
from backend.infrastructure.security import token_issuer as issuer_module
from backend.infrastructure.security.token_issuer import JWTTokenIssuer
from backend.infrastructure.settings import Settings

SECRET = 'test-jwt-secret-with-at-least-32-bytes'


@pytest.fixture
def settings():
    return Settings(_env_file=None, database_url='postgresql+asyncpg://test:test@localhost/test',
                    jwt_secret_key=SECRET, jwt_access_token_ttl_minutes=5)


@pytest.fixture
def issuer(settings):
    return JWTTokenIssuer(settings)


def claims(settings):
    now = int(datetime.now(timezone.utc).timestamp())
    return dict(sub=str(uuid4()), iat=now - 1, nbf=now - 1, exp=now + 300,
                iss=settings.jwt_issuer, aud=settings.jwt_audience,
                jti=str(uuid4()), token_type='access')


def test_encode_decode_and_configured_ttl(issuer, settings):
    user_id = uuid4()
    first = issuer.encode(user_id)
    second = issuer.encode(user_id)
    payload = jwt.decode(first, SECRET, algorithms=['HS256'],
                         audience=settings.jwt_audience, issuer=settings.jwt_issuer)
    assert issuer.decode(first) == user_id
    assert payload['sub'] == str(user_id)
    assert payload['token_type'] == 'access'
    assert payload['exp'] - payload['iat'] == 300
    assert payload['nbf'] == payload['iat']
    assert first != second


@pytest.mark.parametrize('field', ['sub', 'iat', 'nbf', 'exp', 'iss', 'aud', 'jti', 'token_type'])
def test_missing_claim_rejected(issuer, settings, field):
    payload = claims(settings)
    del payload[field]
    with pytest.raises(InvalidAccessTokenError):
        issuer.decode(jwt.encode(payload, SECRET, algorithm='HS256'))


@pytest.mark.parametrize(('field', 'value'), [
    ('sub', 'not-a-uuid'), ('sub', 123), ('sub', None),
    ('iss', 'other-service'), ('aud', 'other-api'), ('token_type', 'refresh'),
    ('iat', 'bad'), ('iat', []), ('exp', []), ('nbf', []), ('jti', 123),
])
def test_invalid_claim_rejected(issuer, settings, field, value):
    payload = claims(settings)
    payload[field] = value
    with pytest.raises(InvalidAccessTokenError):
        issuer.decode(jwt.encode(payload, SECRET, algorithm='HS256'))


@pytest.mark.parametrize('field', ['iat', 'nbf'])
def test_future_claim_rejected(issuer, settings, field):
    payload = claims(settings)
    payload[field] += 600
    with pytest.raises(InvalidAccessTokenError):
        issuer.decode(jwt.encode(payload, SECRET, algorithm='HS256'))


@pytest.mark.parametrize(('field', 'value'), [('iat', '1'), ('nbf', '1'), ('exp', '9999999999'), ('iat', True)])
def test_numeric_dates_must_be_integers(issuer, settings, field, value):
    payload = claims(settings)
    payload[field] = value
    with pytest.raises(InvalidAccessTokenError):
        issuer.decode(jwt.encode(payload, SECRET, algorithm='HS256'))


def test_expired_token(issuer, settings):
    payload = claims(settings)
    payload.update(iat=payload['iat'] - 100, exp=payload['iat'] - 10)
    with pytest.raises(AccessTokenExpiredError):
        issuer.decode(jwt.encode(payload, SECRET, algorithm='HS256'))


def test_expiry_exact_boundary_is_expired(issuer, settings, monkeypatch):
    payload = claims(settings)
    expiry = datetime.fromtimestamp(payload['exp'], tz=timezone.utc)
    class FixedDatetime:
        @staticmethod
        def now(tz=None):
            return expiry
    monkeypatch.setattr(issuer_module, 'datetime', FixedDatetime)
    with pytest.raises(AccessTokenExpiredError):
        issuer.decode(jwt.encode(payload, SECRET, algorithm='HS256'))


@pytest.mark.parametrize('token', ['', 'not.a.jwt', 'junk', None, 123])
def test_malformed_token(issuer, token):
    with pytest.raises(InvalidAccessTokenError):
        issuer.decode(token)


def test_wrong_key_and_wrong_algorithm(issuer, settings):
    payload = claims(settings)
    for token in [jwt.encode(payload, 'different-secret-key-at-least-32-bytes', algorithm='HS256'),
                  jwt.encode(payload, SECRET, algorithm='HS384')]:
        with pytest.raises(InvalidAccessTokenError):
            issuer.decode(token)


def test_tampered_payload(issuer, settings):
    token = issuer.encode(uuid4())
    replacement = issuer.encode(uuid4()).split('.')[1]
    header, payload, signature = token.split('.')
    with pytest.raises(InvalidAccessTokenError):
        issuer.decode('.'.join([header, replacement, signature]))


def test_missing_secret_is_configuration_error(settings):
    with pytest.raises(ValueError, match='JWT_SECRET_KEY'):
        JWTTokenIssuer(settings.model_copy(update={'jwt_secret_key': None}))


@pytest.mark.parametrize('secret', ['', 'short', ' ' * 32])
def test_weak_secret_rejected(secret):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url='postgresql+asyncpg://test:test@localhost/test', jwt_secret_key=secret)


def test_unsupported_algorithm_and_nonpositive_ttl_rejected():
    for options in ({'jwt_algorithm': 'none'}, {'jwt_access_token_ttl_minutes': 0}):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, database_url='postgresql+asyncpg://test:test@localhost/test', **options)


def test_encode_requires_uuid(issuer):
    with pytest.raises(TypeError):
        issuer.encode('not-a-uuid')


def test_unsigned_token_rejected(issuer, settings):
    import base64
    import json

    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b'=').decode()
    token = encode({'alg': 'none', 'typ': 'JWT'}) + '.' + encode(claims(settings)) + '.'
    with pytest.raises(InvalidAccessTokenError):
        issuer.decode(token)
