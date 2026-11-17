from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from redis.exceptions import ConnectionError, ResponseError, TimeoutError

from backend.application.share.errors import RateLimiterUnavailableError
from backend.infrastructure.security.rate_limiter import RedisRateLimiter


@pytest.mark.parametrize('error', [ConnectionError, TimeoutError, ResponseError])
async def test_store_errors_are_safe_and_never_allow_request(error):
    script = AsyncMock(side_effect=error('redis://private:secret@host'))
    limiter = RedisRateLimiter(SimpleNamespace(register_script=lambda _: script))
    with pytest.raises(RateLimiterUnavailableError) as raised:
        await limiter.consume('alice@example.com', limit=3, window=timedelta(minutes=1))
    assert 'secret' not in str(raised.value)


@pytest.mark.parametrize('limit,window', [
    (0, timedelta(seconds=1)), (-1, timedelta(seconds=1)),
    (True, timedelta(seconds=1)), (1.5, timedelta(seconds=1)),
    (2 ** 53, timedelta(seconds=1)), (1, timedelta(0)),
    (1, timedelta(seconds=-1)), (1, 1), (1, timedelta.max),
])
async def test_invalid_budget_never_contacts_store(limit, window):
    script = AsyncMock()
    limiter = RedisRateLimiter(SimpleNamespace(register_script=lambda _: script))
    with pytest.raises(ValueError):
        await limiter.consume('key', limit=limit, window=window)
    script.assert_not_awaited()


async def test_sub_millisecond_window_rounds_up_and_identifier_is_not_sent():
    script = AsyncMock(return_value=0)
    limiter = RedisRateLimiter(SimpleNamespace(register_script=lambda _: script))
    assert await limiter.consume('alice@example.com', limit=1, window=timedelta(microseconds=1)) == 0
    assert script.call_args.kwargs['args'] == [1, 1]
    assert 'alice' not in script.call_args.kwargs['keys'][0]
