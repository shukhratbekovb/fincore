import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.infrastructure.health import check_dependencies


def dependencies(pg_value=1, redis_value=True):
    connection = SimpleNamespace(scalar=AsyncMock(return_value=pg_value))
    manager = AsyncMock()
    manager.__aenter__.return_value = connection
    engine = SimpleNamespace(connect=Mock(return_value=manager))
    redis = SimpleNamespace(ping=AsyncMock(return_value=redis_value))
    return engine, redis, connection, manager


async def test_readiness_uses_a_lightweight_database_query_and_redis_ping():
    engine, redis, connection, manager = dependencies()
    assert await check_dependencies(engine, redis, timeout=0.1) == {'postgres': 'ok', 'redis': 'ok'}
    assert str(connection.scalar.await_args.args[0]) == 'SELECT 1'
    redis.ping.assert_awaited_once_with()
    manager.__aexit__.assert_awaited_once()


@pytest.mark.parametrize('dependency', ['postgres', 'redis'])
@pytest.mark.parametrize('problem', ['false', 'exception', 'timeout'])
async def test_each_failed_dependency_is_reported_without_exception_details(dependency, problem):
    engine, redis, connection, manager = dependencies()
    method = connection.scalar if dependency == 'postgres' else redis.ping
    if problem == 'false':
        method.return_value = 0 if dependency == 'postgres' else False
    elif problem == 'exception':
        method.side_effect = RuntimeError('postgresql://admin:password@private-host/database')
    else:
        async def pending(*args):
            await asyncio.Event().wait()
        method.side_effect = pending
    result = await check_dependencies(engine, redis, timeout=0.01)
    assert result[dependency] == 'unavailable'
    assert result['redis' if dependency == 'postgres' else 'postgres'] == 'ok'
    assert 'password' not in str(result) and 'private-host' not in str(result)
    manager.__aexit__.assert_awaited_once()


async def test_both_probes_start_concurrently_instead_of_serially():
    engine, redis, connection, _ = dependencies()
    pg_started, redis_started = asyncio.Event(), asyncio.Event()
    async def postgres(*args):
        pg_started.set()
        await redis_started.wait()
        return 1
    async def ping():
        redis_started.set()
        await pg_started.wait()
        return True
    connection.scalar.side_effect = postgres
    redis.ping.side_effect = ping
    assert await check_dependencies(engine, redis, timeout=0.1) == {'postgres': 'ok', 'redis': 'ok'}


async def test_shutdown_cancellation_is_not_converted_to_unavailable():
    engine, redis, connection, _ = dependencies()
    started = asyncio.Event()
    async def pending(*args):
        started.set()
        await asyncio.Event().wait()
    connection.scalar.side_effect = pending
    task = asyncio.create_task(check_dependencies(engine, redis, timeout=10))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
