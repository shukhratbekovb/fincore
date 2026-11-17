from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from backend.application.auth.dtos.register import RegisterUserResult
from backend.application.auth.dtos.token import TokenResult
from backend.application.auth.errors import InvalidCredentialsError
from backend.application.share.errors import RateLimiterUnavailableError
from backend.application.transfer.dtos.create_transfer import CreateTransferResult
from backend.infrastructure.security.token_issuer import JWTTokenIssuer
from backend.infrastructure.settings import Settings, get_settings
from backend.main import app
from backend.presentation.api.v1.dependencies.auth import get_login_use_case, get_register_use_case
from backend.presentation.api.v1.dependencies.finance import get_create_transfer_use_case
from backend.presentation.api.v1.dependencies.rate_limit import get_rate_limiter


def override_with(value):
    return lambda: value


@pytest.fixture
async def limits_context(monkeypatch):
    settings = Settings(_env_file=None, database_url='postgresql+asyncpg://localhost/fincore_test',
                        jwt_secret_key='http-request-limits-test-secret-' * 2)
    limiter = SimpleNamespace(consume=AsyncMock(return_value=0))
    cases = {
        'login': SimpleNamespace(execute=AsyncMock(return_value=TokenResult('access', 'refresh'))),
        'register': SimpleNamespace(execute=AsyncMock(return_value=RegisterUserResult(uuid4()))),
        'transfer': SimpleNamespace(execute=AsyncMock(return_value=CreateTransferResult(uuid4()))),
    }
    for dependency, value in (
        (get_settings, settings), (get_rate_limiter, limiter),
        (get_login_use_case, cases['login']), (get_register_use_case, cases['register']),
        (get_create_transfer_use_case, cases['transfer']),
    ):
        monkeypatch.setitem(app.dependency_overrides, dependency, override_with(value))
    actor = uuid4()
    headers = {'Authorization': 'Bearer ' + JWTTokenIssuer(settings).encode(actor), 'Idempotency-Key': 'same-request'}
    bodies = {
        'login': {'username': 'Alice', 'password': 'wrong-password'},
        'register': {'username': 'Alice', 'email': 'ALICE@example.com'},
        'transfer': {'sender_wallet_id': str(uuid4()), 'receiver_wallet_id': str(uuid4()), 'amount_minor': '1', 'currency': 'USD'},
    }
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url='http://test') as client:
        yield SimpleNamespace(client=client, limiter=limiter, settings=settings, cases=cases,
                              bodies=bodies, headers=headers, actor=actor)


def path(kind):
    return '/v1/transfers' if kind == 'transfer' else '/v1/auth/' + kind


@pytest.mark.parametrize('kind', ['login', 'register', 'transfer'])
@pytest.mark.parametrize('budget', [[17], [0, 23]])
async def test_either_budget_blocks_before_any_use_case(limits_context, kind, budget):
    ctx = limits_context
    ctx.limiter.consume.side_effect = budget
    response = await ctx.client.post(path(kind), json=ctx.bodies[kind], headers=ctx.headers)
    assert response.status_code == 429
    assert response.headers['retry-after'] == str(budget[-1])
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['detail']['message'] == 'Too many requests'
    assert ctx.limiter.consume.await_count == len(budget)
    for case in ctx.cases.values():
        case.execute.assert_not_awaited()


@pytest.mark.parametrize('kind', ['login', 'register', 'transfer'])
@pytest.mark.parametrize('allowed_first_budget', [False, True])
async def test_redis_failure_returns_503_without_business_side_effects(limits_context, kind, allowed_first_budget):
    ctx = limits_context
    ctx.limiter.consume.side_effect = ([0] if allowed_first_budget else []) + [RateLimiterUnavailableError()]
    response = await ctx.client.post(path(kind), json=ctx.bodies[kind], headers=ctx.headers)
    assert response.status_code == 503
    assert response.json()['detail']['code'] == 'rate_limiter_unavailable'
    assert response.headers['cache-control'] == 'no-store'
    for case in ctx.cases.values():
        case.execute.assert_not_awaited()


@pytest.mark.parametrize('kind,status', [('login', 200), ('register', 201), ('transfer', 201)])
async def test_allowed_requests_use_configured_budgets_and_normalized_identifiers(limits_context, kind, status):
    ctx = limits_context
    ctx.settings.login_rate_limit_ip_per_minute = 7
    ctx.settings.login_rate_limit_username_per_minute = 4
    ctx.settings.register_rate_limit_ip_per_hour = 6
    ctx.settings.register_rate_limit_email_per_hour = 2
    ctx.settings.transfer_rate_limit_ip_per_minute = 9
    ctx.settings.transfer_rate_limit_user_per_minute = 3
    response = await ctx.client.post(path(kind), json=ctx.bodies[kind], headers={**ctx.headers, 'x-forwarded-for': '203.0.113.9'})
    assert response.status_code == status, response.text
    calls = ctx.limiter.consume.call_args_list
    expected = {
        'login': [('login-ip:127.0.0.1', 7, 60), ('login-username:alice', 4, 60)],
        'register': [('register-ip:127.0.0.1', 6, 3600), ('register-email:alice@example.com', 2, 3600)],
        'transfer': [('transfer-ip:127.0.0.1', 9, 60), (f'transfer-user:{ctx.actor}', 3, 60)],
    }[kind]
    assert [(call.args[0], call.kwargs['limit'], call.kwargs['window'].total_seconds()) for call in calls] == expected
    ctx.cases[kind].execute.assert_awaited_once()


@pytest.mark.parametrize('authorization', [None, 'Bearer invalid-token'])
async def test_transfer_authentication_precedes_redis(limits_context, authorization):
    ctx = limits_context
    ctx.limiter.consume.side_effect = RateLimiterUnavailableError()
    headers = {'Idempotency-Key': 'test'}
    if authorization:
        headers['Authorization'] = authorization
    response = await ctx.client.post(path('transfer'), json=ctx.bodies['transfer'], headers=headers)
    assert response.status_code == 401
    ctx.limiter.consume.assert_not_awaited()
    ctx.cases['transfer'].execute.assert_not_awaited()


async def test_invalid_credentials_still_consume_both_request_budgets(limits_context):
    ctx = limits_context
    ctx.cases['login'].execute.side_effect = InvalidCredentialsError()
    response = await ctx.client.post(path('login'), json=ctx.bodies['login'])
    assert response.status_code == 401
    assert ctx.limiter.consume.await_count == 2


async def test_registration_requires_resolvable_client_address(limits_context):
    ctx = limits_context
    async with AsyncClient(transport=ASGITransport(app=app, client=None), base_url='http://test') as client:
        response = await client.post(path('register'), json=ctx.bodies['register'])
    assert response.status_code == 400
    ctx.limiter.consume.assert_not_awaited()
    ctx.cases['register'].execute.assert_not_awaited()
