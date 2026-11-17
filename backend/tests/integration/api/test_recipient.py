from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from backend.application.share.errors import RateLimiterUnavailableError
from backend.application.wallet.dtos.resolve_recipient import WalletRecipientDTO
from backend.domain.share.enums import CurrencyEnum
from backend.infrastructure.security.token_issuer import JWTTokenIssuer
from backend.infrastructure.settings import Settings, get_settings
from backend.main import app
from backend.presentation.api.v1.dependencies.core import get_uow
from backend.presentation.api.v1.dependencies.rate_limit import get_rate_limiter

PATH = '/v1/transfer-recipients/resolve'


@pytest.fixture
async def ctx(monkeypatch):
    user = SimpleNamespace(id=uuid4(), is_active=lambda: True)
    recipient = WalletRecipientDTO(uuid4(), '00001234567890123456', CurrencyEnum.CAD, 'recipient_user')
    uow = AsyncMock()
    uow.users.get_by_id.return_value = user
    uow.wallet_reader.get_recipient_by_number.return_value = recipient
    limiter = SimpleNamespace(consume=AsyncMock(return_value=0))
    settings = Settings(_env_file=None, database_url='postgresql+asyncpg://localhost/fincore_test', jwt_secret_key='wallet-recipient-api-test-key-' * 2)
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: settings)
    monkeypatch.setitem(app.dependency_overrides, get_uow, lambda: uow)
    monkeypatch.setitem(app.dependency_overrides, get_rate_limiter, lambda: limiter)
    headers = {'Authorization': 'Bearer ' + JWTTokenIssuer(settings).encode(user.id)}
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        yield SimpleNamespace(client=client, user=user, recipient=recipient, uow=uow, limiter=limiter, settings=settings,
                              headers=headers, body={'wallet_number': recipient.number})


async def test_exact_contract_preserves_zeroes_and_exposes_only_recipient_username(ctx):
    response = await ctx.client.post(PATH, json=ctx.body, headers=ctx.headers)
    assert response.status_code == 200
    assert response.json() == {'wallet_id': str(ctx.recipient.wallet_id), 'number': ctx.recipient.number,
                               'currency': 'CAD', 'owner': 'recipient_user'}
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-request-id']
    calls = ctx.limiter.consume.await_args_list
    assert calls[0].args[0].startswith('recipient-lookup-ip:')
    assert calls[1].args[0] == f'recipient-lookup-user:{ctx.user.id}'
    assert all(ctx.recipient.number not in call.args[0] for call in calls)


@pytest.mark.parametrize('value', [12345678901234567890, '', '1' * 19, '1' * 21, '０' * 20, 'a' * 20, ' ' + '0' * 20])
async def test_requires_exact_ascii_string_number(ctx, value):
    response = await ctx.client.post(PATH, json={'wallet_number': value}, headers=ctx.headers)
    assert response.status_code == 422
    ctx.uow.wallet_reader.get_recipient_by_number.assert_not_awaited()


async def test_rejects_spoofed_owner_in_request(ctx):
    response = await ctx.client.post(PATH, json=ctx.body | {'owner': 'attacker'}, headers=ctx.headers)
    assert response.status_code == 422


@pytest.mark.parametrize('headers', [{}, {'Authorization': 'Bearer invalid'}])
async def test_requires_authentication_before_limiter_or_reader(ctx, headers):
    response = await ctx.client.post(PATH, json=ctx.body, headers=headers)
    assert response.status_code == 401
    ctx.limiter.consume.assert_not_awaited()
    ctx.uow.wallet_reader.get_recipient_by_number.assert_not_awaited()


async def test_not_found_and_inactive_actor(ctx):
    ctx.uow.wallet_reader.get_recipient_by_number.return_value = None
    response = await ctx.client.post(PATH, json=ctx.body, headers=ctx.headers)
    assert response.status_code == 404 and response.json()['detail']['code'] == 'wallet_not_found'
    ctx.uow.users.get_by_id.return_value = SimpleNamespace(is_active=lambda: False)
    response = await ctx.client.post(PATH, json=ctx.body, headers=ctx.headers)
    assert response.status_code == 403


@pytest.mark.parametrize('failure', ['ip', 'user', 'unavailable'])
async def test_lookup_fails_closed_on_limit_or_redis_failure(ctx, failure):
    if failure == 'unavailable':
        ctx.limiter.consume.side_effect = RateLimiterUnavailableError()
    else:
        ctx.limiter.consume.side_effect = [9] if failure == 'ip' else [0, 9]
    response = await ctx.client.post(PATH, json=ctx.body, headers=ctx.headers)
    assert response.status_code == (503 if failure == 'unavailable' else 429)
    if response.status_code == 429:
        assert response.headers['retry-after'] == '9'
    ctx.uow.wallet_reader.get_recipient_by_number.assert_not_awaited()
