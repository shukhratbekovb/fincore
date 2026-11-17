from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from backend.application.auth.dtos.password_reset import ConfirmPasswordResetResult
from backend.application.auth.errors import InvalidPasswordResetTokenError
from backend.main import app
from backend.presentation.api.v1.dependencies.auth import (
    get_confirm_password_reset_use_case, get_request_password_reset_use_case,
)
from backend.presentation.api.v1.dependencies.rate_limit import get_rate_limiter


@pytest.fixture
async def reset_context(monkeypatch):
    request = SimpleNamespace(execute=AsyncMock())
    confirm = SimpleNamespace(execute=AsyncMock(return_value=ConfirmPasswordResetResult('GeneratedPassword1!')))
    limiter = SimpleNamespace(consume=AsyncMock(return_value=0))
    def override(value):
        return lambda: value
    for dependency, value in [(get_request_password_reset_use_case, request),
                              (get_confirm_password_reset_use_case, confirm), (get_rate_limiter, limiter)]:
        monkeypatch.setitem(app.dependency_overrides, dependency, override(value))
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url='http://test') as client:
        yield SimpleNamespace(client=client, request=request, confirm=confirm, limiter=limiter)


async def test_request_returns_generic_202_and_normalizes_email(reset_context):
    ctx = reset_context
    results = []
    for email in ('Alice@example.com', 'unknown@example.com'):
        response = await ctx.client.post('/v1/auth/password-reset/request', json={'email': email})
        assert response.status_code == 202
        assert response.headers['cache-control'] == 'no-store'
        assert ctx.request.execute.call_args.kwargs['cmd'].email.value == email.lower()
        results.append(response.json())
    assert results[0] == results[1] == {'message': 'If the account is eligible, a password reset email will be sent.'}
    assert ctx.limiter.consume.call_count == 4


async def test_confirmation_returns_password_and_no_store(reset_context):
    ctx = reset_context
    response = await ctx.client.post('/v1/auth/password-reset/confirm', json={'token': 'reset-secret'})
    assert response.status_code == 200
    assert response.json() == {'password': 'GeneratedPassword1!'}
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['pragma'] == 'no-cache'
    command = ctx.confirm.execute.call_args.kwargs['cmd']
    assert command.token == 'reset-secret'
    assert 'reset-secret' not in repr(command)


async def test_password_is_not_cached_behind_proxy_path_prefix(reset_context):
    async with AsyncClient(
        transport=ASGITransport(app=app, root_path='/gateway'), base_url='http://test',
    ) as client:
        response = await client.post('/gateway/v1/auth/password-reset/confirm', json={'token': 'reset-secret'})
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'


async def test_invalid_reset_is_generic_and_not_cached(reset_context):
    ctx = reset_context
    ctx.confirm.execute.side_effect = InvalidPasswordResetTokenError()
    response = await ctx.client.post('/v1/auth/password-reset/confirm', json={'token': 'reset-secret'})
    assert response.status_code == 400
    assert response.json()['detail']['code'] == 'invalid_password_reset_token'
    assert response.headers['cache-control'] == 'no-store'
    assert 'reset-secret' not in response.text


@pytest.mark.parametrize('endpoint,body', [
    ('request', {'email': 'not-an-email'}), ('confirm', {'token': ''}),
    ('confirm', {'token': 'has spaces'}), ('confirm', {'token': 'x' * 513}),
    ('confirm', {'token': 'secret', 'password': 'MustNotUse1!'}), ('confirm', {}),
])
async def test_invalid_reset_body_does_not_reach_use_case_or_echo_secrets(reset_context, endpoint, body):
    ctx = reset_context
    response = await ctx.client.post('/v1/auth/password-reset/' + endpoint, json=body)
    assert response.status_code == 422
    assert response.headers['cache-control'] == 'no-store'
    assert 'MustNotUse1!' not in response.text
    assert 'secret' not in response.text
    ctx.request.execute.assert_not_awaited()
    ctx.confirm.execute.assert_not_awaited()


@pytest.mark.parametrize('endpoint,budgets', [('request', [31]), ('request', [0, 180]), ('confirm', [42])])
async def test_rate_limit_rejects_before_work_and_returns_retry_after(reset_context, endpoint, budgets):
    ctx = reset_context
    ctx.limiter.consume.side_effect = budgets
    body = {'email': 'alice@example.com'} if endpoint == 'request' else {'token': 'secret'}
    response = await ctx.client.post('/v1/auth/password-reset/' + endpoint, json=body)
    assert response.status_code == 429
    assert response.headers['retry-after'] == str(budgets[-1])
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['detail']['message'] == 'Too many requests'
    ctx.request.execute.assert_not_awaited()
    ctx.confirm.execute.assert_not_awaited()


async def test_reset_get_does_not_consume_token(reset_context):
    ctx = reset_context
    response = await ctx.client.get('/v1/auth/password-reset/confirm?token=secret')
    assert response.status_code == 405
    ctx.confirm.execute.assert_not_awaited()


async def test_untrusted_forwarded_ip_does_not_change_limit_key(reset_context):
    ctx = reset_context
    await ctx.client.post('/v1/auth/password-reset/confirm', json={'token': 'secret'},
                          headers={'x-forwarded-for': '8.8.8.8'})
    assert ctx.limiter.consume.call_args.args[0] == 'reset-confirm-ip:127.0.0.1'


@pytest.mark.parametrize('endpoint,body', [('request', {'email': 'alice@example.com'}), ('confirm', {'token': 'secret'})])
async def test_unavailable_store_returns_safe_503_before_use_case(reset_context, endpoint, body):
    from backend.application.share.errors import RateLimiterUnavailableError
    ctx = reset_context
    ctx.limiter.consume.side_effect = RateLimiterUnavailableError()
    response = await ctx.client.post('/v1/auth/password-reset/' + endpoint, json=body)
    assert response.status_code == 503
    assert response.json()['detail']['code'] == 'rate_limiter_unavailable'
    assert response.headers['cache-control'] == 'no-store'
    ctx.request.execute.assert_not_awaited()
    ctx.confirm.execute.assert_not_awaited()
