from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from backend.application.auth.dtos.token import TokenResult
from backend.presentation.api.v1.dependencies.auth import get_login_use_case, get_refresh_use_case
from backend.presentation.api.v1.dependencies.client import ClientInfoDep
from backend.presentation.api.v1.routers.auth import router
from backend.presentation.api.v1.dependencies.rate_limit import get_rate_limiter
from backend.infrastructure.settings import Settings, get_settings


@pytest.mark.parametrize('ip_address', ['198.51.100.20', '2001:db8::20'])
@pytest.mark.parametrize('user_agent', ['Browser/1.0', None])
async def test_client_info_uses_connection_and_optional_user_agent(ip_address, user_agent):
    app = FastAPI()

    @app.get('/client-info')
    def endpoint(client_info: ClientInfoDep):
        return client_info

    headers = {'x-forwarded-for': '203.0.113.99', 'x-real-ip': '203.0.113.99'}
    async with AsyncClient(
        transport=ASGITransport(app=app, client=(ip_address, 12345)), base_url='http://test',
    ) as client:
        # HTTPX supplies its own User-Agent unless explicitly removed.
        client.headers.pop('user-agent')
        if user_agent is not None:
            headers['user-agent'] = user_agent
        response = await client.get('/client-info', headers=headers)

    assert response.status_code == 200
    assert response.json() == {'ip_address': ip_address, 'user_agent': user_agent}


async def test_missing_client_address_returns_bad_request():
    app = FastAPI()

    @app.get('/client-info')
    def endpoint(client_info: ClientInfoDep):
        return client_info

    async with AsyncClient(
        transport=ASGITransport(app=app, client=None), base_url='http://test',
    ) as client:
        response = await client.get('/client-info')

    assert response.status_code == 400
    assert response.json() == {'detail': 'Cannot determine client IP'}


@pytest.mark.parametrize('peer,forwarded,expected_ip', [
    ('172.30.85.2', '198.51.100.20', '198.51.100.20'),
    ('172.30.85.2', '2001:db8::20', '2001:db8::20'),
    # Neither a sibling container nor an external peer can supply the client IP.
    ('172.30.85.4', '198.51.100.20', '172.30.85.4'),
    ('203.0.113.50', '198.51.100.20', '203.0.113.50'),
    # Even an unexpected appended chain uses the nearest untrusted address.
    ('172.30.85.2', '192.0.2.99, 198.51.100.20', '198.51.100.20'),
])
async def test_docker_api_trusts_only_the_frontend_peer(peer, forwarded, expected_ip):
    app = FastAPI()

    @app.get('/client-info')
    def endpoint(client_info: ClientInfoDep):
        return client_info

    proxy_app = ProxyHeadersMiddleware(app, trusted_hosts=['172.30.85.2'])
    async with AsyncClient(
        transport=ASGITransport(app=proxy_app, client=(peer, 12345)), base_url='http://test',
    ) as client:
        response = await client.get('/client-info', headers={
            'x-forwarded-for': forwarded,
            'x-real-ip': '192.0.2.88',
            'user-agent': 'Browser/1.0',
        })

    assert response.status_code == 200
    assert response.json() == {'ip_address': expected_ip, 'user_agent': 'Browser/1.0'}


@pytest.mark.parametrize('peer,expected_ip', [
    ('127.0.0.1', '198.51.100.20'),
    ('203.0.113.50', '203.0.113.50'),
])
@pytest.mark.parametrize('path,body,dependency', [
    ('/auth/login', {'username': 'bobur', 'password': 'StrongPassword1!'}, get_login_use_case),
    ('/auth/refresh', {'refresh_token': 'old-refresh'}, get_refresh_use_case),
])
async def test_auth_commands_use_client_info_with_proxy_trust(peer, expected_ip, path, body, dependency):
    app = FastAPI()
    app.include_router(router)
    limiter = SimpleNamespace(consume=AsyncMock(return_value=0))
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, database_url='postgresql+asyncpg://localhost/test')
    use_case = AsyncMock()
    use_case.execute.return_value = TokenResult(access_token='access', refresh_token='refresh')
    app.dependency_overrides[dependency] = lambda: use_case
    # Match the Uvicorn configuration used by `make serve`.
    proxy_app = ProxyHeadersMiddleware(app, trusted_hosts=['127.0.0.1'])

    async with AsyncClient(
        transport=ASGITransport(app=proxy_app, client=(peer, 12345)), base_url='http://test',
    ) as client:
        response = await client.post(
            path,
            json={**body, 'ip_address': '192.0.2.99', 'user_agent': 'forged body agent'},
            headers={'x-forwarded-for': '198.51.100.20', 'user-agent': 'Browser/1.0'},
        )

    assert response.status_code == 200
    assert response.json() == {'access_token': 'access', 'refresh_token': 'refresh'}
    use_case.execute.assert_awaited_once()
    command = use_case.execute.call_args.kwargs['cmd']
    assert command.ip_address == expected_ip
    assert command.user_agent == 'Browser/1.0'
    if path == '/auth/login':
        assert limiter.consume.call_args_list[0].args[0] == f'login-ip:{expected_ip}'
        assert command.username.value == body['username']
        assert command.password.value == body['password']
    else:
        assert command.refresh_token == body['refresh_token']
