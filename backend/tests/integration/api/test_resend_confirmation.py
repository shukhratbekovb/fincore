from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from backend.application.share.errors import RateLimiterUnavailableError
from backend.infrastructure.settings import Settings, get_settings
from backend.main import app
from backend.presentation.api.v1.dependencies.auth import get_resend_confirmation_use_case
from backend.presentation.api.v1.dependencies.rate_limit import get_rate_limiter


@pytest.fixture
async def resend_context(monkeypatch):
    case = SimpleNamespace(execute=AsyncMock())
    limiter = SimpleNamespace(consume=AsyncMock(return_value=0))
    settings = Settings(_env_file=None, database_url='postgresql+asyncpg://localhost/fincore_test')
    def override(value):
        return lambda: value
    for dependency, value in [(get_resend_confirmation_use_case, case), (get_rate_limiter, limiter), (get_settings, settings)]:
        monkeypatch.setitem(app.dependency_overrides, dependency, override(value))
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url='http://test') as client:
        yield SimpleNamespace(client=client, case=case, limiter=limiter)


async def test_public_generic_response_normalized_email_and_no_store(resend_context):
    ctx = resend_context
    results = []
    for email in ['Alice@example.com', 'unknown@example.com']:
        response = await ctx.client.post('/v1/auth/confirm/resend', json={'email': email})
        assert response.status_code == 202
        assert response.headers['cache-control'] == 'no-store'
        assert ctx.case.execute.call_args.kwargs['cmd'].email.value == email.lower()
        results.append(response.json())
    assert results[0] == results[1] == {
        'message': 'If the account is awaiting confirmation, a new confirmation email will be sent.',
    }
    assert ctx.limiter.consume.call_args_list[1].args == ('confirmation-resend-email:alice@example.com',)


@pytest.mark.parametrize('budgets', [[20], [0, 60]])
async def test_limits_prevent_work_and_return_retry_after(resend_context, budgets):
    ctx = resend_context
    ctx.limiter.consume.side_effect = budgets
    response = await ctx.client.post('/v1/auth/confirm/resend', json={'email': 'alice@example.com'})
    assert response.status_code == 429
    assert response.headers['retry-after'] == str(budgets[-1])
    ctx.case.execute.assert_not_awaited()


async def test_redis_unavailable_fails_closed(resend_context):
    ctx = resend_context
    ctx.limiter.consume.side_effect = RateLimiterUnavailableError()
    response = await ctx.client.post('/v1/auth/confirm/resend', json={'email': 'alice@example.com'})
    assert response.status_code == 503
    assert response.json()['detail']['code'] == 'rate_limiter_unavailable'
    ctx.case.execute.assert_not_awaited()


@pytest.mark.parametrize('body', [{}, {'email': 'invalid'}, {'email': 'alice@example.com', 'token': 'secret'}])
async def test_invalid_input_is_rejected_without_echoing_tokens(resend_context, body):
    ctx = resend_context
    response = await ctx.client.post('/v1/auth/confirm/resend', json=body)
    assert response.status_code == 422
    assert 'secret' not in response.text
    ctx.case.execute.assert_not_awaited()


async def test_forwarded_header_cannot_spoof_rate_limit_ip(resend_context):
    ctx = resend_context
    await ctx.client.post('/v1/auth/confirm/resend', json={'email': 'alice@example.com'},
                          headers={'x-forwarded-for': '8.8.8.8'})
    assert ctx.limiter.consume.call_args_list[0].args == ('confirmation-resend-ip:127.0.0.1',)
