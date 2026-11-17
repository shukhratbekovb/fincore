from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.presentation.api.health import router


@pytest.mark.parametrize('path', ['/health', '/health/live'])
async def test_liveness_works_without_lifespan_database_or_redis(path):
    application = FastAPI()
    application.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=application), base_url='http://test') as client:
        response = await client.get(path)
    assert response.status_code == 200 and response.json() == {'status': 'ok'}
    assert response.headers['content-type'] == 'application/json'


@pytest.mark.parametrize('postgres_ok,redis_ok', [(True, True), (False, True), (True, False), (False, False)])
async def test_readiness_contract_uses_real_probes_and_hides_connection_secrets(postgres_ok, redis_ok):
    application = FastAPI()
    application.include_router(router)
    connection = SimpleNamespace(scalar=AsyncMock(return_value=1))
    manager = AsyncMock()
    manager.__aenter__.return_value = connection
    if not postgres_ok:
        connection.scalar.side_effect = RuntimeError('postgres://admin:pg-secret@private-host/fincore')
    application.state.engine = SimpleNamespace(connect=Mock(return_value=manager))
    application.state.redis_client = SimpleNamespace(ping=AsyncMock(return_value=True))
    if not redis_ok:
        application.state.redis_client.ping.side_effect = RuntimeError('redis://admin:redis-secret@private-host')
    application.state.health_check_timeout = 0.1
    async with AsyncClient(transport=ASGITransport(app=application), base_url='http://test') as client:
        response = await client.get('/health/ready')
    ready = postgres_ok and redis_ok
    assert response.status_code == (200 if ready else 503)
    assert response.json() == {'status': 'ok' if ready else 'unavailable', 'checks': {
        'postgres': 'ok' if postgres_ok else 'unavailable', 'redis': 'ok' if redis_ok else 'unavailable'}}
    assert response.headers['cache-control'] == 'no-store'
    assert 'secret' not in response.text and 'private-host' not in response.text


async def test_readiness_is_unavailable_when_application_resources_are_not_initialized():
    application = FastAPI()
    application.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=application), base_url='http://test') as client:
        response = await client.get('/health/ready')
    assert response.status_code == 503
    assert response.json()['checks'] == {'postgres': 'unavailable', 'redis': 'unavailable'}


async def test_health_disallows_post_and_public_openapi_exposes_contract_without_lifespan():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/health')
        assert response.status_code == 405
        schema = (await client.get('/openapi.json')).json()
    assert schema['info']['title'] == 'FinCore API'
    for path in ('/health', '/health/live', '/health/ready'):
        assert 'get' in schema['paths'][path]
    assert '503' in schema['paths']['/health/ready']['get']['responses']
