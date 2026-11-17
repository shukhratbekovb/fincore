from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from backend.application.auth.dtos.register import RegisterUserResult
from backend.application.auth.errors import InvalidCredentialsError
from backend.application.transfer.dtos.create_transfer import CreateTransferResult
from backend.infrastructure.security.token_issuer import JWTTokenIssuer
from backend.infrastructure.settings import Settings, get_settings
from backend.main import app
from backend.presentation.api.v1.dependencies.auth import get_login_use_case, get_register_use_case
from backend.presentation.api.v1.dependencies.finance import get_create_transfer_use_case


def override_with(value):
    return lambda: value


@pytest.fixture
async def protected_context(redis_context, monkeypatch):
    settings = Settings(_env_file=None, database_url='postgresql+asyncpg://localhost/fincore_test',
                        jwt_secret_key='real-redis-request-limits-tests-' * 2,
                        login_rate_limit_ip_per_minute=3, login_rate_limit_username_per_minute=2,
                        register_rate_limit_ip_per_hour=3, register_rate_limit_email_per_hour=2,
                        transfer_rate_limit_ip_per_minute=5, transfer_rate_limit_user_per_minute=2)
    login = SimpleNamespace(execute=AsyncMock(side_effect=InvalidCredentialsError()))
    register = SimpleNamespace(execute=AsyncMock(return_value=RegisterUserResult(uuid4())))
    transfer = SimpleNamespace(execute=AsyncMock(return_value=CreateTransferResult(uuid4())))
    monkeypatch.setattr(app.state, 'rate_limiter', redis_context.limiter, raising=False)
    for dependency, value in ((get_settings, settings), (get_login_use_case, login),
                              (get_register_use_case, register), (get_create_transfer_use_case, transfer)):
        monkeypatch.setitem(app.dependency_overrides, dependency, override_with(value))
    async with AsyncClient(transport=ASGITransport(app=app, client=('192.0.2.1', 1)), base_url='http://test') as first:
        async with AsyncClient(transport=ASGITransport(app=app, client=('192.0.2.2', 1)), base_url='http://test') as second:
            yield SimpleNamespace(first=first, second=second, login=login, register=register,
                                  transfer=transfer, issuer=JWTTokenIssuer(settings))


async def test_login_username_budget_survives_ip_and_case_changes(protected_context):
    ctx = protected_context
    async def login(client, name):
        return await client.post('/v1/auth/login', json={'username': name, 'password': 'wrong-password'})
    assert (await login(ctx.first, 'alice')).status_code == 401
    assert (await login(ctx.first, 'ALICE')).status_code == 401
    blocked = await login(ctx.second, 'Alice')
    assert blocked.status_code == 429 and 1 <= int(blocked.headers['retry-after']) <= 60
    assert (await login(ctx.first, 'bobby')).status_code == 401
    # Changing the account cannot bypass the IP budget either.
    assert (await login(ctx.first, 'other')).status_code == 429
    assert ctx.login.execute.await_count == 3


async def test_registration_email_and_ip_budgets_are_both_enforced(protected_context):
    ctx = protected_context
    async def register(client, email):
        return await client.post('/v1/auth/register', json={'username': 'alice', 'email': email})
    assert (await register(ctx.first, 'alice@example.com')).status_code == 201
    assert (await register(ctx.first, 'ALICE@example.com')).status_code == 201
    blocked = await register(ctx.second, 'Alice@example.com')
    assert blocked.status_code == 429 and 1 <= int(blocked.headers['retry-after']) <= 3600
    assert (await register(ctx.first, 'other@example.com')).status_code == 201
    assert (await register(ctx.first, 'another@example.com')).status_code == 429
    assert ctx.register.execute.await_count == 3


async def test_transfer_user_budget_covers_all_keys_and_ips(protected_context):
    ctx = protected_context
    first_token = ctx.issuer.encode(uuid4())
    second_token = ctx.issuer.encode(uuid4())
    body = {'sender_wallet_id': str(uuid4()), 'receiver_wallet_id': str(uuid4()), 'amount_minor': '1', 'currency': 'USD'}
    async def transfer(client, token, key):
        return await client.post('/v1/transfers', json=body,
                                 headers={'Authorization': 'Bearer ' + token, 'Idempotency-Key': key})
    assert (await transfer(ctx.first, first_token, 'first')).status_code == 201
    assert (await transfer(ctx.first, first_token, 'second')).status_code == 201
    assert (await transfer(ctx.first, first_token, 'first')).status_code == 429
    # Another user has a separate budget; another IP does not give the first user a new one.
    assert (await transfer(ctx.first, second_token, 'first')).status_code == 201
    assert (await transfer(ctx.second, first_token, 'third')).status_code == 429
    assert (await transfer(ctx.first, second_token, 'second')).status_code == 201
    assert (await transfer(ctx.first, ctx.issuer.encode(uuid4()), 'another')).status_code == 429
    assert ctx.transfer.execute.await_count == 4
