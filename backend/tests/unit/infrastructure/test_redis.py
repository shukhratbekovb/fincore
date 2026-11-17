from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import ssl

import pytest

from backend.infrastructure.redis import create_redis_client
from backend.infrastructure.settings import Settings


def test_client_uses_bounded_pool_timeouts_and_no_automatic_write_retry():
    settings = Settings(_env_file=None, database_url='postgresql+asyncpg://localhost/test',
                        redis_url='rediss://user:private-secret@localhost:6379/1',
                        redis_max_connections=7, redis_socket_timeout=2, redis_connect_timeout=3)
    client = create_redis_client(settings)
    config = client.connection_pool.connection_kwargs
    assert client.connection_pool.max_connections == 7
    assert config['socket_timeout'] == 2 and config['socket_connect_timeout'] == 3
    assert config['retry'].get_retries() == 0
    connection = client.connection_pool.connection_class(**config)
    context = connection.ssl_context.get()
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert 'private-secret' not in repr(settings)


@pytest.mark.parametrize('failure', ['none', 'during_request', 'during_setup', 'during_close'])
async def test_lifespan_releases_resources_and_clears_state(monkeypatch, failure):
    import backend.main as main
    engine = SimpleNamespace(dispose=AsyncMock())
    redis = SimpleNamespace(aclose=AsyncMock(), register_script=Mock())
    monkeypatch.setattr(main, 'create_engine', lambda _: engine)
    def create_client(_):
        if failure == 'during_setup':
            raise RuntimeError('setup failed')
        return redis
    monkeypatch.setattr(main, 'create_redis_client', create_client)
    if failure == 'during_close':
        redis.aclose.side_effect = RuntimeError('close failed')
    app = SimpleNamespace(state=SimpleNamespace())
    async def run():
        async with main.lifespan(app):
            assert app.state.rate_limiter is not None
            if failure == 'during_request':
                raise RuntimeError('request failed')
    if failure == 'none':
        await run()
    else:
        with pytest.raises(RuntimeError):
            await run()
    engine.dispose.assert_awaited_once()
    if failure != 'during_setup':
        redis.aclose.assert_awaited_once()
    assert app.state.rate_limiter is app.state.engine is app.state.session_factory is None
