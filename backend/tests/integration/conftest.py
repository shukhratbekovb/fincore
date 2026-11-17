import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.infrastructure.redis import create_redis_client
from backend.infrastructure.settings import Settings
from backend.infrastructure.security.rate_limiter import RedisRateLimiter


@pytest.fixture
async def redis_context():
    url = os.environ.get('FINCORE_TEST_REDIS_URL')
    if not url:
        pytest.skip('Set FINCORE_TEST_REDIS_URL to a dedicated Redis test instance')
    settings = Settings(_env_file=None, database_url='postgresql+asyncpg://localhost/fincore_test',
                        redis_url=url, redis_max_connections=128)
    client = create_redis_client(settings)
    prefix = 'fincore:test:rate-limit:' + uuid4().hex + ':'
    try:
        await client.ping()
        yield SimpleNamespace(client=client, prefix=prefix, settings=settings,
                              limiter=RedisRateLimiter(client, key_prefix=prefix))
    finally:
        try:
            # Never FLUSHDB: delete only keys owned by this test.
            keys = [key async for key in client.scan_iter(match=prefix + '*')]
            if keys:
                await client.delete(*keys)
        finally:
            await client.aclose()
