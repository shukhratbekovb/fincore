import hashlib
from datetime import timedelta

from redis.asyncio import Redis
from redis.exceptions import RedisError

from backend.application.share.errors import RateLimiterUnavailableError


# A window starts on the first request. Rejections do not extend it.
# Decision, increment and expiry must execute together.
CONSUME_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local current = redis.call('GET', key)
if not current then
    redis.call('SET', key, 1, 'PX', window_ms)
    return 0
end
local ttl = redis.call('PTTL', key)
if ttl < 1 then
    redis.call('PEXPIRE', key, window_ms)
    ttl = window_ms
end
if tonumber(current) >= limit then
    return math.max(1, math.ceil(ttl / 1000))
end
redis.call('INCR', key)
return 0
"""


class RedisRateLimiter:
    def __init__(self, client: Redis, *, key_prefix: str = 'fincore:rate-limit:v1:'):
        self._consume = client.register_script(CONSUME_SCRIPT)
        self._key_prefix = key_prefix

    async def consume(self, key: str, *, limit: int, window: timedelta) -> int:
        if type(limit) is not int or not 0 < limit <= 2 ** 53 - 1:
            raise ValueError('Rate limit must be a positive safe integer')
        if not isinstance(window, timedelta) or window <= timedelta(0):
            raise ValueError('Rate limit window must be positive')
        microseconds = window // timedelta(microseconds=1)
        window_ms = (microseconds + 999) // 1000
        if window_ms > 2 ** 53 - 1:
            raise ValueError('Rate limit window is too large')
        digest = hashlib.sha256(key.encode()).hexdigest()
        try:
            result = await self._consume(keys=[self._key_prefix + digest], args=[limit, window_ms])
        except RedisError:
            # Do not expose connection URLs, credentials or raw limit keys.
            raise RateLimiterUnavailableError() from None
        return int(result)
