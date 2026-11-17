from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from backend.domain.session.entities import RefreshToken, Session
from backend.domain.user.entities import User
from backend.domain.user.value_objects import Email, HashedPassword, Username
from backend.infrastructure.db.sqlalchemy.core.uow import SqlAlchemyUnitOfWork
from backend.infrastructure.security.token_hasher import TokenHasher
from backend.infrastructure.security.token_issuer import JWTTokenIssuer
from backend.infrastructure.settings import Settings, get_settings
from backend.main import app
from backend.presentation.api.v1.dependencies.core import get_clock


async def test_profile_and_session_management_over_http_and_postgresql(session_factory, monkeypatch, now):
    username = 'user' + uuid4().hex[:12]
    user = User.created_by_admin(Username(username), Email(username + '@example.com'), HashedPassword('unused-hash'))
    other = User.created_by_admin(Username('otheruser'), Email('other@example.com'), HashedPassword('unused-hash'))
    first = Session.create(user_id=user.id, ip_address='192.0.2.1', now=now - timedelta(hours=2), ttl=timedelta(days=1))
    second = Session.create(user_id=user.id, ip_address='192.0.2.2', now=now - timedelta(hours=1), ttl=timedelta(days=1))
    expired = Session.create(user_id=user.id, ip_address='192.0.2.3', now=now - timedelta(hours=1), ttl=timedelta(hours=1))
    revoked = Session.create(user_id=user.id, ip_address='192.0.2.4', now=now - timedelta(hours=1), ttl=timedelta(days=1))
    revoked.revoke(now=now - timedelta(minutes=30))
    foreign = Session.create(user_id=other.id, ip_address='192.0.2.5', now=now, ttl=timedelta(days=1))
    hasher = TokenHasher()
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.users.add(user)
        await uow.users.add(other)
        for session in (first, second, expired, revoked, foreign):
            await uow.sessions.add(session)
        for session, token in ((first, 'first-refresh'), (second, 'second-refresh')):
            await uow.refresh_tokens.add(RefreshToken(
                session_id=session.id, token_hash=hasher.hash(token), expires_at=session.expires_at,
            ))
        await uow.commit()

    settings = Settings(_env_file=None, database_url='postgresql+asyncpg://localhost/fincore_test',
                        jwt_secret_key='user-router-db-test-secret-' * 3)
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: settings)
    monkeypatch.setitem(app.dependency_overrides, get_clock, lambda: SimpleNamespace(now=lambda: now))
    monkeypatch.setattr(app.state, 'session_factory', session_factory, raising=False)
    headers = {'Authorization': 'Bearer ' + JWTTokenIssuer(settings).encode(user.id)}

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get('/v1/users/me', headers=headers)
        assert response.status_code == 200
        assert response.json()['id'] == str(user.id)
        assert response.json()['username'] == username
        assert response.json()['email'] == user.email.value
        assert 'unused-hash' not in response.text
        assert response.headers['cache-control'] == 'no-store'

        response = await client.get('/v1/users/me/sessions', headers=headers)
        assert response.status_code == 200
        assert [item['id'] for item in response.json()] == [str(second.id), str(first.id)]
        assert expired.expires_at == now

        foreign_response = await client.delete('/v1/users/me/sessions/' + str(foreign.id), headers=headers)
        missing_response = await client.delete('/v1/users/me/sessions/' + str(uuid4()), headers=headers)
        assert foreign_response.status_code == missing_response.status_code == 404
        assert foreign_response.json() == missing_response.json()
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            assert (await uow.sessions.get_by_id(foreign.id)).revoked_at is None

        for _ in range(2):
            response = await client.delete('/v1/users/me/sessions/' + str(first.id), headers=headers)
            assert response.status_code == 204 and response.content == b''
        assert (await client.post('/v1/auth/refresh', json={'refresh_token': 'first-refresh'})).status_code == 401
        # The second session can still refresh after revoking only the first.
        response = await client.post('/v1/auth/refresh', json={'refresh_token': 'second-refresh'})
        assert response.status_code == 200
        replacement_refresh = response.json()['refresh_token']
        response = await client.get('/v1/users/me/sessions', headers=headers)
        assert [item['id'] for item in response.json()] == [str(second.id)]
        assert response.json()[0]['last_used_at'] is not None

        for _ in range(2):
            response = await client.delete('/v1/users/me/sessions', headers=headers)
            assert response.status_code == 204 and response.content == b''
            assert response.headers['cache-control'] == 'no-store'
        assert (await client.post('/v1/auth/refresh', json={'refresh_token': replacement_refresh})).status_code == 401
        # Existing access JWTs still authenticate; revocation currently blocks refresh.
        response = await client.get('/v1/users/me/sessions', headers=headers)
        assert response.status_code == 200 and response.json() == []

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        assert (await uow.sessions.get_by_id(first.id)).revoked_at == now
        assert (await uow.sessions.get_by_id(second.id)).revoked_at == now
        assert (await uow.sessions.get_by_id(revoked.id)).revoked_at == revoked.revoked_at
        assert (await uow.sessions.get_by_id(foreign.id)).revoked_at is None
