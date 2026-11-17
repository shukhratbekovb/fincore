from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

from backend.infrastructure.settings import Settings


def create_redis_client(settings: Settings) -> Redis:
    """Create a lazy shared pool, closed by the application's lifespan."""
    return Redis.from_url(
        settings.redis_url.get_secret_value(),
        socket_connect_timeout=settings.redis_connect_timeout,
        socket_timeout=settings.redis_socket_timeout,
        max_connections=settings.redis_max_connections,
        decode_responses=False,
        # A lost reply may follow an executed increment. Do not retry writes.
        retry=Retry(NoBackoff(), 0),
    )
