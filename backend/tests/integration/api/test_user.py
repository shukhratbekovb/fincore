from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt

from backend.domain.session.entities import Session
from backend.domain.user.entities import User
from backend.domain.user.value_objects import Email, HashedPassword, Username
from backend.infrastructure.security.token_issuer import JWTTokenIssuer
from backend.infrastructure.settings import Settings, get_settings
from backend.main import app
from backend.presentation.api.v1.dependencies.core import get_clock, get_uow
from backend.presentation.api.v1.schemas.user import SessionResponse, UserResponse

SECRET = 'user-router-test-secret-' * 3
ROUTES = [('GET', '/v1/users/me'), ('GET', '/v1/users/me/sessions'),
          ('DELETE', '/v1/users/me/sessions'), ('DELETE', '/v1/users/me/sessions/{session_id}')]


@pytest.fixture
async def user_context(monkeypatch, now):
    user = User.created_by_admin(Username('alice'), Email('alice@example.com'), HashedPassword('private-hash'))
    session = Session.create(user_id=user.id, ip_address='192.0.2.10', now=now, ttl=timedelta(days=30), user_agent='Example Browser')
    uow = AsyncMock()
    uow.users.get_by_id.return_value = user
    uow.users.get_by_id_for_update.return_value = user
    uow.sessions.get_active_by_user_id.return_value = [session]
    uow.sessions.get_by_id_for_update.return_value = session
    factory = Mock(return_value=uow)
    clock = SimpleNamespace(now=lambda: now)
    settings = Settings(_env_file=None, database_url='postgresql+asyncpg://localhost/fincore_test', jwt_secret_key=SECRET)
    monkeypatch.setitem(app.dependency_overrides, get_uow, lambda: factory())
    monkeypatch.setitem(app.dependency_overrides, get_clock, lambda: clock)
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: settings)
    issuer = JWTTokenIssuer(settings)
    token = issuer.encode(user.id)
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url='http://test') as client:
        yield SimpleNamespace(client=client, user=user, session=session, uow=uow, factory=factory,
                              headers={'Authorization': 'Bearer ' + token}, token=token, now=now)


async def test_profile_serializes_value_objects_and_excludes_credentials(user_context):
    ctx = user_context
    response = await ctx.client.get('/v1/users/me', headers=ctx.headers)
    assert response.status_code == 200
    profile = UserResponse.model_validate(response.json())
    assert profile.id == ctx.user.id
    assert profile.username == 'alice' and profile.email == 'alice@example.com'
    assert profile.created_at == ctx.user.created_at
    assert set(response.json()) == {'id', 'username', 'email', 'created_at'}
    assert 'private-hash' not in response.text
    assert response.headers['cache-control'] == 'no-store'
    ctx.uow.commit.assert_not_awaited()


async def test_sessions_response_contains_only_safe_metadata(user_context):
    ctx = user_context
    response = await ctx.client.get('/v1/users/me/sessions', headers=ctx.headers)
    assert response.status_code == 200
    session = SessionResponse.model_validate(response.json()[0])
    assert session.id == ctx.session.id
    assert session.ip_address == ctx.session.ip_address
    assert session.user_agent == 'Example Browser'
    assert session.created_at == ctx.now and session.last_used_at is None
    assert set(response.json()[0]) == {
        'id', 'expires_at', 'created_at', 'ip_address', 'user_agent',
        'last_used_at', 'last_ip_address', 'last_user_agent',
    }
    ctx.uow.sessions.get_active_by_user_id.assert_awaited_once_with(ctx.user.id, now=ctx.now)
    ctx.uow.commit.assert_not_awaited()


async def test_no_active_sessions_returns_empty_list(user_context):
    ctx = user_context
    ctx.uow.sessions.get_active_by_user_id.return_value = []
    response = await ctx.client.get('/v1/users/me/sessions', headers=ctx.headers)
    assert response.status_code == 200 and response.json() == []


@pytest.mark.parametrize('method,path', ROUTES)
async def test_user_id_always_comes_from_signed_jwt(user_context, method, path):
    ctx = user_context
    path = path.format(session_id=ctx.session.id)
    response = await ctx.client.request(method, path, headers=ctx.headers,
        params={'user_id': str(uuid4())}, json={'user_id': str(uuid4())})
    assert response.status_code == (200 if method == 'GET' else 204)
    if method == 'GET':
        ctx.uow.users.get_by_id.assert_awaited_once_with(ctx.user.id)
    else:
        ctx.uow.users.get_by_id_for_update.assert_awaited_once_with(ctx.user.id)
        assert response.content == b''
        ctx.uow.commit.assert_awaited_once()
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('method,path', ROUTES)
@pytest.mark.parametrize('problem', ['missing', 'invalid', 'expired'])
async def test_authentication_is_required_before_constructing_operations(user_context, method, path, problem):
    ctx = user_context
    headers = {}
    expected_code = 'http_error'
    if problem == 'invalid':
        # A well-formed JWT signed with a different key must be rejected.
        claims = jwt.get_unverified_claims(ctx.token)
        headers = {'Authorization': 'Bearer ' + jwt.encode(claims, 'a-different-test-key-' * 3, algorithm='HS256')}
        expected_code = 'invalid_access_token'
    elif problem == 'expired':
        claims = jwt.get_unverified_claims(ctx.token)
        stamp = int(datetime.now(timezone.utc).timestamp())
        claims.update(iat=stamp - 120, nbf=stamp - 120, exp=stamp - 60)
        headers = {'Authorization': 'Bearer ' + jwt.encode(claims, SECRET, algorithm='HS256')}
        expected_code = 'access_token_expired'
    response = await ctx.client.request(method, path.format(session_id=ctx.session.id), headers=headers)
    assert response.status_code == 401
    assert response.json()['detail']['code'] == expected_code
    assert response.headers['cache-control'] == 'no-store'
    if problem == 'missing':
        assert response.headers['www-authenticate'] == 'Bearer'
    ctx.factory.assert_not_called()
    ctx.uow.commit.assert_not_awaited()


@pytest.mark.parametrize('method,path', ROUTES)
@pytest.mark.parametrize('problem', ['missing', 'inactive'])
async def test_ineligible_user_cannot_read_or_revoke_sessions(user_context, method, path, problem):
    ctx = user_context
    if problem == 'missing':
        ctx.uow.users.get_by_id.return_value = None
        ctx.uow.users.get_by_id_for_update.return_value = None
    else:
        ctx.user.suspend()
    response = await ctx.client.request(method, path.format(session_id=ctx.session.id), headers=ctx.headers)
    assert response.status_code == (404 if problem == 'missing' else 403)
    assert response.json()['detail']['code'] == ('user_not_found' if problem == 'missing' else 'user_inactive')
    assert response.headers['cache-control'] == 'no-store'
    ctx.uow.sessions.get_active_by_user_id.assert_not_awaited()
    ctx.uow.sessions.get_by_id_for_update.assert_not_awaited()
    ctx.uow.sessions.revoke_all_by_user_id.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()


async def test_revoke_all_uses_authenticated_owner_and_clock(user_context):
    ctx = user_context
    response = await ctx.client.delete('/v1/users/me/sessions', headers=ctx.headers)
    assert response.status_code == 204 and response.content == b''
    ctx.uow.sessions.revoke_all_by_user_id.assert_awaited_once_with(ctx.user.id, now=ctx.now)
    ctx.uow.commit.assert_awaited_once()


async def test_revoke_one_is_idempotent(user_context):
    ctx = user_context
    for _ in range(2):
        response = await ctx.client.delete('/v1/users/me/sessions/' + str(ctx.session.id), headers=ctx.headers)
        assert response.status_code == 204 and response.content == b''
    assert ctx.session.revoked_at == ctx.now
    ctx.uow.sessions.save.assert_awaited_once_with(ctx.session)
    ctx.uow.commit.assert_awaited_once()


@pytest.mark.parametrize('problem', ['missing', 'foreign'])
async def test_foreign_and_missing_sessions_have_same_404_and_are_not_modified(user_context, problem):
    ctx = user_context
    if problem == 'missing':
        ctx.uow.sessions.get_by_id_for_update.return_value = None
    else:
        ctx.session.user_id = uuid4()
    response = await ctx.client.delete('/v1/users/me/sessions/' + str(ctx.session.id), headers=ctx.headers)
    assert response.status_code == 404
    assert response.json()['detail'] == {'code': 'session_not_found', 'message': 'Session not found', 'errors': []}
    assert ctx.session.revoked_at is None
    ctx.uow.sessions.save.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()


async def test_invalid_session_uuid_returns_422_without_revocation(user_context):
    ctx = user_context
    response = await ctx.client.delete('/v1/users/me/sessions/not-a-uuid', headers=ctx.headers)
    assert response.status_code == 422
    issue = response.json()['detail']['errors'][0]
    assert issue['loc'] == ['path', 'session_id']
    ctx.uow.sessions.get_by_id_for_update.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()


async def test_profile_is_not_cached_behind_proxy_prefix(user_context):
    async with AsyncClient(transport=ASGITransport(app=app, root_path='/gateway'), base_url='http://test') as client:
        response = await client.get('/gateway/v1/users/me', headers=user_context.headers)
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
