from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI

from backend import main
from backend.bootstrap import api


@pytest.mark.parametrize('problem', ['none', 'inside', 'session_factory', 'redis_close'])
async def test_api_lifespan_owns_probe_resources_and_releases_them_on_failures(monkeypatch, problem):
    settings = SimpleNamespace(health_check_timeout=0.25)
    engine = SimpleNamespace(dispose=AsyncMock())
    redis = SimpleNamespace(aclose=AsyncMock(), register_script=Mock(return_value=AsyncMock()))
    factory = object()
    create_factory = Mock(return_value=factory)
    monkeypatch.setattr(main, 'get_settings', lambda: settings)
    monkeypatch.setattr(main, 'create_engine', lambda settings: engine)
    monkeypatch.setattr(main, 'create_redis_client', lambda settings: redis)
    monkeypatch.setattr(main, 'create_session_factory', create_factory)
    if problem == 'session_factory':
        create_factory.side_effect = RuntimeError('factory unavailable')
    if problem == 'redis_close':
        redis.aclose.side_effect = RuntimeError('redis close unavailable')
    application = FastAPI()
    async def run():
        async with main.lifespan(application):
            assert application.state.engine is engine and application.state.redis_client is redis
            assert application.state.session_factory is factory
            assert application.state.health_check_timeout == 0.25
            assert application.state.rate_limiter is not None
            if problem == 'inside':
                raise RuntimeError('request failure')
    if problem == 'none':
        await run()
    else:
        with pytest.raises(RuntimeError):
            await run()
    engine.dispose.assert_awaited_once_with()
    redis.aclose.assert_awaited_once_with()
    for name in ('engine', 'session_factory', 'redis_client', 'rate_limiter'):
        assert getattr(application.state, name) is None


def test_api_entrypoint_uses_configured_workers_and_our_logging_without_raw_access_logs(monkeypatch):
    run = Mock()
    monkeypatch.setattr(api, 'get_settings', lambda: SimpleNamespace(log_level='WARNING', api_workers=3))
    monkeypatch.setattr(api.uvicorn, 'run', run)
    api.main()
    args, kwargs = run.call_args
    assert args == ('backend.main:app',)
    assert kwargs['host'] == '0.0.0.0' and kwargs['port'] == 8000 and kwargs['workers'] == 3
    assert kwargs['log_config'] == api.logging_config('WARNING') and kwargs['access_log'] is False
    assert kwargs['server_header'] is False and kwargs['timeout_graceful_shutdown'] >= 30
