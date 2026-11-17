from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from backend.application.auth.dtos.register import RegisterUserResult
from backend.application.auth.dtos.token import TokenResult
from backend.application.auth.errors import (
    AccessTokenExpiredError, EmailAlreadyExistError, InvalidAccessTokenError,
    InvalidCredentialsError, UserInactiveError, UsernameAlreadyExistError,
)
from backend.application.user.errors import UserNotFoundError
from backend.application.verification.errors import VerificationChallengeNotFoundError
from backend.domain.session.errors import InvalidRefreshTokenError, RefreshTokenReuseError
from backend.domain.user.errors import InvalidEmailError, InvalidUsernameError, UserNotPendingConfirmationError
from backend.domain.verification.errors import (
    VerificationChallengeAlreadyUsedError, VerificationChallengeExpiredError,
    VerificationChallengePurposeMismatchError,
)
from backend.main import app
from backend.infrastructure.settings import Settings, get_settings
from backend.presentation.api.v1.dependencies.rate_limit import get_rate_limiter
from backend.presentation.api.v1.dependencies.auth import (
    get_confirm_use_case, get_login_use_case, get_logout_use_case,
    get_refresh_use_case, get_register_use_case,
)


BODIES = {
    'login': {'username': 'alice', 'password': 'Password1!'},
    'register': {'username': 'alice', 'email': 'alice@example.com'},
    'refresh': {'refresh_token': 'refresh-secret'},
    'logout': {'refresh_token': 'refresh-secret'},
    'confirm': {'token': 'confirmation-secret', 'password': 'Password1!'},
}


def override_with(value):
    return lambda: value


@pytest.fixture
async def auth_context(monkeypatch):
    limiter = SimpleNamespace(consume=AsyncMock(return_value=0))
    settings = Settings(_env_file=None, database_url='postgresql+asyncpg://localhost/fincore_test')
    monkeypatch.setitem(app.dependency_overrides, get_rate_limiter, lambda: limiter)
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: settings)
    cases = {}
    user_id = uuid4()
    for name, dependency in [
        ('login', get_login_use_case), ('register', get_register_use_case),
        ('refresh', get_refresh_use_case), ('logout', get_logout_use_case),
        ('confirm', get_confirm_use_case),
    ]:
        case = AsyncMock()
        case.execute.return_value = (
            RegisterUserResult(user_id) if name == 'register'
            else TokenResult('access-token', 'refresh-token') if name in {'login', 'refresh'}
            else None
        )
        cases[name] = case
        monkeypatch.setitem(app.dependency_overrides, dependency, override_with(case))

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url='http://test',
    ) as client:
        yield SimpleNamespace(client=client, cases=cases, user_id=user_id)


@pytest.mark.parametrize('name,status', [
    ('login', 200), ('register', 201), ('refresh', 200), ('logout', 204), ('confirm', 204),
])
async def test_success_contract(auth_context, name, status):
    ctx = auth_context
    response = await ctx.client.post('/v1/auth/' + name, json=BODIES[name])
    assert response.status_code == status
    ctx.cases[name].execute.assert_awaited_once()
    command = ctx.cases[name].execute.call_args.kwargs['cmd']
    if name == 'register':
        assert response.json() == {'user_id': str(ctx.user_id)}
        assert command.username.value == 'alice'
        assert command.email.value == 'alice@example.com'
    elif name in {'login', 'refresh'}:
        assert response.json() == {'access_token': 'access-token', 'refresh_token': 'refresh-token'}
    else:
        assert response.content == b''
        if name == 'confirm':
            assert command.token == 'confirmation-secret'
            assert command.password.value == 'Password1!'
        else:
            assert command.refresh_token == 'refresh-secret'


@pytest.mark.parametrize('name,error,status,code', [
    ('login', InvalidCredentialsError(), 401, 'invalid_credentials'),
    ('login', UserInactiveError(), 403, 'user_inactive'),
    ('login', InvalidUsernameError(['Invalid username']), 422, 'invalid_username'),
    ('login', InvalidAccessTokenError(), 401, 'invalid_access_token'),
    ('login', AccessTokenExpiredError(), 401, 'access_token_expired'),
    ('register', EmailAlreadyExistError(), 409, 'email_already_exists'),
    ('register', UsernameAlreadyExistError(), 409, 'username_already_exists'),
    ('register', InvalidEmailError(), 422, 'invalid_email'),
    ('refresh', InvalidRefreshTokenError(), 401, 'invalid_refresh_token'),
    ('refresh', RefreshTokenReuseError(), 401, 'invalid_refresh_token'),
    ('refresh', UserInactiveError(), 403, 'user_inactive'),
    ('confirm', VerificationChallengeNotFoundError(), 400, 'invalid_confirmation_token'),
    ('confirm', VerificationChallengeExpiredError(), 400, 'confirmation_token_expired'),
    ('confirm', VerificationChallengeAlreadyUsedError(), 400, 'confirmation_token_used'),
    ('confirm', VerificationChallengePurposeMismatchError(), 400, 'invalid_confirmation_token'),
    ('confirm', UserNotPendingConfirmationError(), 409, 'user_not_pending_confirmation'),
    ('confirm', UserNotFoundError(), 404, 'user_not_found'),
])
async def test_expected_errors_have_stable_http_contract(auth_context, name, error, status, code):
    ctx = auth_context
    ctx.cases[name].execute.side_effect = error
    response = await ctx.client.post('/v1/auth/' + name, json=BODIES[name])
    assert response.status_code == status
    detail = response.json()['detail']
    assert detail['code'] == code
    assert detail['message']
    assert isinstance(detail['errors'], list)


@pytest.mark.parametrize('name,field,value', [
    ('register', 'username', 'a'), ('register', 'username', 'alice_'),
    ('register', 'username', 'a' * 257), ('register', 'email', 'invalid'),
    ('login', 'password', ''), ('login', 'password', 'Secret1!' * 40),
    ('login', 'username', '1alice'),
    ('confirm', 'password', 'short'), ('confirm', 'password', 'Secret1!' * 40),
    ('confirm', 'token', ''), ('confirm', 'token', ' '), ('confirm', 'token', 's' * 513),
    ('refresh', 'refresh_token', ''), ('refresh', 'refresh_token', 'has spaces'),
    ('refresh', 'refresh_token', 's' * 513), ('logout', 'refresh_token', ''),
])
async def test_schema_rejects_invalid_input_without_reflecting_secrets(auth_context, name, field, value):
    ctx = auth_context
    response = await ctx.client.post('/v1/auth/' + name, json={**BODIES[name], field: value})
    assert response.status_code == 422
    detail = response.json()['detail']
    assert detail['code'] == 'request_validation_error'
    issue = detail['errors'][0]
    assert issue['loc'] == ['body', field]
    assert set(issue) == {'loc', 'message', 'type'}
    for secret in ('Password1!', 'confirmation-secret', 'refresh-secret', 'Secret1!' * 40):
        assert secret not in response.text
    ctx.cases[name].execute.assert_not_awaited()


async def test_new_password_policy_violation_is_422(auth_context):
    response = await auth_context.client.post(
        '/v1/auth/confirm', json={**BODIES['confirm'], 'password': 'oldpassword'},
    )
    assert response.status_code == 422
    detail = response.json()['detail']
    assert detail['code'] == 'invalid_password'
    assert detail['errors']
    assert all(issue['loc'] == ['body', 'password'] for issue in detail['errors'])
    assert 'oldpassword' not in response.text
    auth_context.cases['confirm'].execute.assert_not_awaited()


async def test_login_verifies_password_without_new_password_policy(auth_context):
    ctx = auth_context
    ctx.cases['login'].execute.side_effect = InvalidCredentialsError()
    response = await ctx.client.post('/v1/auth/login', json={'username': 'alice', 'password': 'oldpassword'})
    assert response.status_code == 401
    assert ctx.cases['login'].execute.call_args.kwargs['cmd'].password.value == 'oldpassword'


async def test_unexpected_error_remains_server_error(auth_context):
    auth_context.cases['login'].execute.side_effect = RuntimeError('sensitive database details')
    response = await auth_context.client.post('/v1/auth/login', json=BODIES['login'])
    assert response.status_code == 500
    assert 'sensitive database details' not in response.text


async def test_missing_client_ip_has_consistent_error_contract(auth_context):
    async with AsyncClient(
        transport=ASGITransport(app=app, client=None), base_url='http://test',
    ) as client:
        response = await client.post('/v1/auth/login', json=BODIES['login'])
    assert response.status_code == 400
    assert response.json()['detail'] == {
        'code': 'http_error', 'message': 'Cannot determine client IP', 'errors': [],
    }
    auth_context.cases['login'].execute.assert_not_awaited()


async def test_openapi_describes_auth_statuses_and_constraints(auth_context):
    response = await auth_context.client.get('/openapi.json')
    assert response.status_code == 200
    schema = response.json()
    for name, success, errors in [
        ('login', '200', ['400', '401', '403', '422']),
        ('register', '201', ['409', '422']),
        ('refresh', '200', ['400', '401', '403', '422']),
        ('logout', '204', ['422']),
        ('confirm', '204', ['400', '404', '409', '422']),
    ]:
        responses = schema['paths']['/v1/auth/' + name]['post']['responses']
        assert success in responses
        if success == '204':
            assert 'content' not in responses[success]
        for status in errors:
            assert responses[status]['content']['application/json']['schema'] == {
                '$ref': '#/components/schemas/ErrorResponse',
            }
    schemas = schema['components']['schemas']
    assert schemas['LoginUserSchema']['properties']['password']['minLength'] == 1
    assert schemas['LoginUserSchema']['properties']['password']['maxLength'] == 256
    assert schemas['ConfirmUserSchema']['properties']['password']['minLength'] == 8
    assert schemas['RefreshSessionSchema']['properties']['refresh_token']['maxLength'] == 512
