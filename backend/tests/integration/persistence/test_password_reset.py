import asyncio
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from backend.application.auth.dtos.password_reset import ConfirmPasswordResetCommand, RequestPasswordResetCommand
from backend.application.auth.errors import InvalidPasswordResetTokenError
from backend.application.auth.use_cases.confirm_password_reset import ConfirmPasswordResetUseCase
from backend.application.auth.use_cases.request_password_reset import RequestPasswordResetUseCase
from backend.domain.session.entities import Session
from backend.domain.user.entities import User
from backend.domain.user.value_objects import Email, RawPassword, Username
from backend.domain.verification.entities import VerificationChallenge
from backend.domain.verification.enums import VerificationPurpose
from backend.infrastructure.clock import SystemClock
from backend.infrastructure.db.sqlalchemy.core.uow import SqlAlchemyUnitOfWork
from backend.infrastructure.db.sqlalchemy.models import SqlAlchemyOutboxModel
from backend.infrastructure.db.sqlalchemy.repository.outbox import SqlAlchemyOutbox
from backend.infrastructure.security.password_generator import PasswordGenerator
from backend.infrastructure.security.password_hasher import Argon2PasswordHasher
from backend.infrastructure.security.token_generator import TokenGenerator
from backend.infrastructure.security.token_hasher import TokenHasher


async def seed_user(factory):
    name = 'user' + uuid4().hex[:12]
    user = User.created_by_admin(Username(name), Email(name + '@example.com'), Argon2PasswordHasher().hash(RawPassword('OldPassword1!')))
    session = Session.create(user_id=user.id, ip_address='127.0.0.1', now=datetime.now(timezone.utc), ttl=timedelta(days=1))
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.users.add(user)
        await uow.sessions.add(session)
        await uow.commit()
    return user, session


def confirm_case(factory):
    return ConfirmPasswordResetUseCase(SqlAlchemyUnitOfWork(factory), PasswordGenerator(),
                                      Argon2PasswordHasher(), TokenHasher(), SystemClock())


async def issue_link(factory, user):
    case = RequestPasswordResetUseCase(SqlAlchemyUnitOfWork(factory), TokenGenerator(), TokenHasher(), SystemClock(), timedelta(minutes=15))
    await case.execute(RequestPasswordResetCommand(user.email))
    async with factory() as session:
        message = (await session.execute(select(SqlAlchemyOutboxModel).order_by(SqlAlchemyOutboxModel.created_at.desc()))).scalars().first()
        return message.payload['token']


async def test_other_links_and_sessions_are_invalidated_preserving_other_purposes(session_factory):
    user, old_session = await seed_user(session_factory)
    first = await issue_link(session_factory, user)
    second = await issue_link(session_factory, user)
    now = datetime.now(timezone.utc)
    registration = VerificationChallenge(user_id=user.id, purpose=VerificationPurpose.REGISTRATION,
        token_hash='registration', expires_at=now + timedelta(hours=1))
    consumed = VerificationChallenge(user_id=user.id, purpose=VerificationPurpose.PASSWORD_RESET,
        token_hash='used', expires_at=now + timedelta(hours=1), used_at=now - timedelta(minutes=1))
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.verification_challenges.add(registration)
        await uow.verification_challenges.add(consumed)
        await uow.commit()
    result = await confirm_case(session_factory).execute(ConfirmPasswordResetCommand(first))
    hasher = Argon2PasswordHasher()
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        saved = await uow.users.get_by_id(user.id)
        assert hasher.verify(RawPassword(result.password), saved.password_hash)
        assert not hasher.verify(RawPassword('OldPassword1!'), saved.password_hash)
        assert (await uow.sessions.get_by_id(old_session.id)).revoked_at is not None
        assert (await uow.verification_challenges.get_by_token_hash('registration')).used_at is None
        assert (await uow.verification_challenges.get_by_token_hash('used')).used_at == consumed.used_at
    for token in (first, second, 'registration'):
        with pytest.raises(InvalidPasswordResetTokenError):
            await confirm_case(session_factory).execute(ConfirmPasswordResetCommand(token))


@pytest.mark.parametrize('same_link', [True, False])
async def test_concurrent_resets_have_one_winner_and_do_not_deadlock(session_factory, same_link):
    user, _ = await seed_user(session_factory)
    first = await issue_link(session_factory, user)
    second = first if same_link else await issue_link(session_factory, user)
    results = await asyncio.wait_for(asyncio.gather(
        confirm_case(session_factory).execute(ConfirmPasswordResetCommand(first)),
        confirm_case(session_factory).execute(ConfirmPasswordResetCommand(second)),
        return_exceptions=True,
    ), timeout=10)
    assert sum(isinstance(result, InvalidPasswordResetTokenError) for result in results) == 1
    winner = next(result for result in results if not isinstance(result, Exception))
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        saved = await uow.users.get_by_id(user.id)
        assert Argon2PasswordHasher().verify(RawPassword(winner.password), saved.password_hash)


async def test_notification_failure_rolls_back_password_links_and_revocation(session_factory, monkeypatch):
    user, old_session = await seed_user(session_factory)
    token = await issue_link(session_factory, user)
    async def fail(self, message):
        raise RuntimeError('outbox unavailable')
    monkeypatch.setattr(SqlAlchemyOutbox, 'add', fail)
    with pytest.raises(RuntimeError):
        await confirm_case(session_factory).execute(ConfirmPasswordResetCommand(token))
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        saved = await uow.users.get_by_id(user.id)
        assert saved.password_hash == user.password_hash
        assert (await uow.sessions.get_by_id(old_session.id)).revoked_at is None
        challenge = await uow.verification_challenges.get_by_token_hash(TokenHasher().hash(token))
        assert challenge.used_at is None


async def test_http_reset_real_smtp_new_password_login_and_notification(session_factory, redis_context, monkeypatch):
    smtp_port, mailpit_url = os.environ.get('FINCORE_TEST_SMTP_PORT'), os.environ.get('FINCORE_TEST_MAILPIT_URL')
    if not smtp_port or not mailpit_url:
        pytest.skip('Set disposable Mailpit settings to test real email delivery')
    from backend.main import app
    from backend.bootstrap.outbox_worker import build_processor
    from backend.infrastructure.notifications.settings import SmtpSettings, OutboxWorkerSettings
    from backend.infrastructure.settings import Settings, get_settings

    user, _ = await seed_user(session_factory)
    settings = Settings(_env_file=None, database_url='postgresql+asyncpg://localhost/fincore_test', jwt_secret_key='local-test-secret-' * 3)
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: settings)
    monkeypatch.setattr(app.state, 'session_factory', session_factory, raising=False)
    monkeypatch.setattr(app.state, 'rate_limiter', redis_context.limiter, raising=False)
    processor = build_processor(session_factory, SmtpSettings(_env_file=None, smtp_port=int(smtp_port),
        frontend_password_reset_url='http://localhost:3000/reset-password'), OutboxWorkerSettings(_env_file=None))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        login = await client.post('/v1/auth/login', json={'username': user.username.value, 'password': 'OldPassword1!'})
        assert login.status_code == 200
        old_refresh = login.json()['refresh_token']
        accepted = await client.post('/v1/auth/password-reset/request', json={'email': user.email.value})
        assert accepted.status_code == 202
        unknown = await client.post('/v1/auth/password-reset/request', json={'email': 'missing@example.com'})
        assert unknown.status_code == 202 and unknown.json() == accepted.json()
        assert await processor.run_once() == 1
        async with AsyncClient(base_url=mailpit_url) as mailbox:
            messages = (await mailbox.get('/api/v1/messages')).json()['messages']
            sent = next(item for item in messages if any(to['Address'] == user.email.value for to in item['To']))
            mail = (await mailbox.get('/api/v1/message/' + sent['ID'])).json()
        url = re.search(r'http://localhost:3000/reset-password#[^\s]+', mail['Text']).group()
        token = parse_qs(urlsplit(url).fragment)['token'][0]
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            assert (await uow.users.get_by_id(user.id)).password_hash == user.password_hash
        response = await client.post('/v1/auth/password-reset/confirm', json={'token': token})
        assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
        password = RawPassword(response.json()['password'])
        assert (await client.post('/v1/auth/password-reset/confirm', json={'token': token})).status_code == 400
        assert (await client.post('/v1/auth/login', json={'username': user.username.value, 'password': 'OldPassword1!'})).status_code == 401
        assert (await client.post('/v1/auth/login', json={'username': user.username.value, 'password': password.value})).status_code == 200
        assert (await client.post('/v1/auth/refresh', json={'refresh_token': old_refresh})).status_code == 401
        async with session_factory() as session:
            notice = (await session.execute(select(SqlAlchemyOutboxModel).where(SqlAlchemyOutboxModel.message_type == 'auth.send_password_changed_notification.v1'))).scalar_one()
            assert set(notice.payload) == {'user_id', 'email', 'changed_at'}
        assert await processor.run_once() == 1
        async with AsyncClient(base_url=mailpit_url) as mailbox:
            messages = (await mailbox.get('/api/v1/messages')).json()['messages']
            notices = [item for item in messages if any(to['Address'] == user.email.value for to in item['To'])]
            assert len(notices) == 2
            for item in notices:
                content = (await mailbox.get('/api/v1/message/' + item['ID'])).json()
                assert password.value not in content['Text'] and password.value not in content['HTML']
        async with session_factory() as session:
            assert await session.scalar(select(func.count()).select_from(SqlAlchemyOutboxModel).where(SqlAlchemyOutboxModel.payload.is_not(None))) == 0
