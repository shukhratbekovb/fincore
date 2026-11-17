import asyncio
import hashlib
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient

from backend.application.auth.dtos.password_reset import ConfirmPasswordResetResult
from backend.infrastructure.redis import create_redis_client
from backend.infrastructure.security.rate_limiter import RedisRateLimiter
from backend.main import app
from backend.presentation.api.v1.dependencies.auth import get_request_password_reset_use_case, get_confirm_password_reset_use_case


async def test_atomic_budget_shared_between_independent_pools(redis_context):
    ctx = redis_context
    other = create_redis_client(ctx.settings)
    try:
        limiters = [ctx.limiter, RedisRateLimiter(other, key_prefix=ctx.prefix)]
        results = await asyncio.gather(*(limiters[i % 2].consume(
            'reset:alice@example.com', limit=3, window=timedelta(minutes=15),
        ) for i in range(100)))
        assert results.count(0) == 3
        assert all(1 <= value <= 900 for value in results if value)
        keys = [key async for key in ctx.client.scan_iter(match=ctx.prefix + '*')]
        assert len(keys) == 1 and b'alice' not in keys[0]
        assert await ctx.client.get(keys[0]) == b'3'
        assert 0 < await ctx.client.pttl(keys[0]) <= 900000
    finally:
        await other.aclose()


async def test_expiry_resets_budget_and_rejections_do_not_extend_window(redis_context):
    ctx = redis_context
    key = ctx.prefix + hashlib.sha256(b'one').hexdigest()
    assert await ctx.limiter.consume('one', limit=1, window=timedelta(seconds=10)) == 0
    await ctx.client.pexpire(key, 150)
    assert await ctx.limiter.consume('one', limit=1, window=timedelta(seconds=10)) == 1
    assert 0 < await ctx.client.pttl(key) <= 150
    async with asyncio.timeout(2):
        while await ctx.client.exists(key):
            await asyncio.sleep(0.01)
    assert await ctx.limiter.consume('one', limit=1, window=timedelta(seconds=10)) == 0
    assert await ctx.client.get(key) == b'1'


async def test_missing_ttl_is_repaired_without_resetting_used_budget(redis_context):
    ctx = redis_context
    key = ctx.prefix + hashlib.sha256(b'one').hexdigest()
    await ctx.client.set(key, 3)
    assert await ctx.limiter.consume('one', limit=3, window=timedelta(seconds=2)) == 2
    assert await ctx.client.get(key) == b'3'
    assert 0 < await ctx.client.pttl(key) <= 2000
    assert await ctx.limiter.consume('other', limit=3, window=timedelta(seconds=2)) == 0


async def test_http_reset_uses_redis_and_stops_before_use_case(redis_context, monkeypatch):
    request = SimpleNamespace(execute=AsyncMock())
    confirm = SimpleNamespace(execute=AsyncMock(return_value=ConfirmPasswordResetResult('GeneratedPassword1!')))
    monkeypatch.setitem(app.dependency_overrides, get_request_password_reset_use_case, lambda: request)
    monkeypatch.setitem(app.dependency_overrides, get_confirm_password_reset_use_case, lambda: confirm)
    monkeypatch.setattr(app.state, 'rate_limiter', redis_context.limiter, raising=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        for _ in range(3):
            assert (await client.post('/v1/auth/password-reset/request', json={'email': 'alice@example.com'})).status_code == 202
        blocked = await client.post('/v1/auth/password-reset/request', json={'email': 'ALICE@example.com'})
        assert blocked.status_code == 429
        assert 1 <= int(blocked.headers['retry-after']) <= 900
        assert blocked.headers['cache-control'] == 'no-store'
        assert request.execute.await_count == 3
        # The confirmation has an independent budget.
        for _ in range(20):
            assert (await client.post('/v1/auth/password-reset/confirm', json={'token': 'secret'})).status_code == 200
        blocked = await client.post('/v1/auth/password-reset/confirm', json={'token': 'secret'})
        assert blocked.status_code == 429
        assert confirm.execute.await_count == 20
