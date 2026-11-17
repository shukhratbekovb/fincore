import asyncio

from sqlalchemy import text


async def check_dependencies(engine, redis_client, *, timeout: float) -> dict[str, str]:
    async def postgres():
        async with engine.connect() as connection:
            return await connection.scalar(text('SELECT 1')) == 1

    async def redis():
        return await redis_client.ping() is True

    async def probe(check):
        try:
            async with asyncio.timeout(timeout):
                return 'ok' if await check() else 'unavailable'
        except Exception:
            # Public health responses must not contain connection details.
            return 'unavailable'

    pg_status, redis_status = await asyncio.gather(probe(postgres), probe(redis))
    return {'postgres': pg_status, 'redis': redis_status}
