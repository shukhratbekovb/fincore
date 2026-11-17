import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.application.auth.dtos.confirm import ConfirmUserCommand
from backend.application.auth.dtos.register import RegisterUserCommand
from backend.application.auth.dtos.resend_confirmation import ResendRegistrationConfirmationCommand
from backend.application.auth.use_cases.confirm import ConfirmUserUseCase
from backend.application.auth.use_cases.register import RegisterUserUseCase
from backend.application.auth.use_cases.resend_confirmation import ResendRegistrationConfirmationUseCase
from backend.domain.user.enums import UserStatusEnum
from backend.domain.user.value_objects import Email, RawPassword, Username
from backend.domain.verification.entities import VerificationChallenge
from backend.domain.verification.enums import VerificationPurpose
from backend.domain.verification.errors import VerificationChallengeAlreadyUsedError
from backend.infrastructure.clock import SystemClock
from backend.infrastructure.db.sqlalchemy.core.uow import SqlAlchemyUnitOfWork
from backend.infrastructure.db.sqlalchemy.models import SqlAlchemyOutboxModel, SqlAlchemyVerificationChallengeModel
from backend.infrastructure.db.sqlalchemy.repository.outbox import SqlAlchemyOutbox
from backend.infrastructure.security.password_hasher import Argon2PasswordHasher
from backend.infrastructure.security.token_generator import TokenGenerator
from backend.infrastructure.security.token_hasher import TokenHasher


def resend_case(factory):
    return ResendRegistrationConfirmationUseCase(
        SqlAlchemyUnitOfWork(factory), TokenGenerator(), TokenHasher(), SystemClock(), timedelta(hours=1),
    )


def confirm_case(factory):
    return ConfirmUserUseCase(SqlAlchemyUnitOfWork(factory), Argon2PasswordHasher(), TokenHasher(), SystemClock())


async def seed(factory):
    username = Username('user' + uuid4().hex[:12])
    email = Email(username.value + '@example.com')
    case = RegisterUserUseCase(SqlAlchemyUnitOfWork(factory), TokenGenerator(), TokenHasher(), SystemClock(), timedelta(hours=1))
    user = await case.execute(RegisterUserCommand(username, email))
    async with factory() as session:
        outbox = (await session.scalars(select(SqlAlchemyOutboxModel))).one()
        return user.user_id, email, outbox.payload['token']


async def test_replacement_invalidates_old_link_and_keeps_other_purposes(session_factory):
    user_id, email, old = await seed(session_factory)
    other = VerificationChallenge(user_id=user_id, purpose=VerificationPurpose.PASSWORD_RESET,
        token_hash='other', expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.verification_challenges.add(other)
        await uow.commit()
    await resend_case(session_factory).execute(ResendRegistrationConfirmationCommand(email))
    async with session_factory() as session:
        messages = (await session.scalars(select(SqlAlchemyOutboxModel).order_by(SqlAlchemyOutboxModel.created_at))).all()
        new = messages[-1].payload['token']
        assert len(messages) == 2 and new != old
    with pytest.raises(VerificationChallengeAlreadyUsedError):
        await confirm_case(session_factory).execute(ConfirmUserCommand(old, RawPassword('Password1!')))
    await confirm_case(session_factory).execute(ConfirmUserCommand(new, RawPassword('Password1!')))
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        assert (await uow.users.get_by_id(user_id)).status == UserStatusEnum.ACTIVE
        assert (await uow.verification_challenges.get_by_token_hash('other')).used_at is None


async def test_outbox_failure_rolls_back_invalidation_and_new_challenge(session_factory, monkeypatch):
    user_id, email, old = await seed(session_factory)
    async def fail(self, message):
        raise RuntimeError('outbox unavailable')
    monkeypatch.setattr(SqlAlchemyOutbox, 'add', fail)
    with pytest.raises(RuntimeError):
        await resend_case(session_factory).execute(ResendRegistrationConfirmationCommand(email))
    async with session_factory() as session:
        challenges = (await session.scalars(select(SqlAlchemyVerificationChallengeModel))).all()
        assert len(challenges) == 1 and challenges[0].used_at is None
    await confirm_case(session_factory).execute(ConfirmUserCommand(old, RawPassword('Password1!')))


async def test_concurrent_resends_leave_one_valid_challenge(session_factory):
    user_id, email, _ = await seed(session_factory)
    await asyncio.wait_for(asyncio.gather(*[
        resend_case(session_factory).execute(ResendRegistrationConfirmationCommand(email)) for _ in range(2)
    ]), timeout=10)
    async with session_factory() as session:
        challenges = (await session.scalars(select(SqlAlchemyVerificationChallengeModel))).all()
        assert len(challenges) == 3
        assert sum(challenge.used_at is None for challenge in challenges) == 1


async def test_concurrent_confirm_and_resend_do_not_deadlock_or_reactivate_account(session_factory):
    user_id, email, old = await seed(session_factory)
    results = await asyncio.wait_for(asyncio.gather(
        confirm_case(session_factory).execute(ConfirmUserCommand(old, RawPassword('Password1!'))),
        resend_case(session_factory).execute(ResendRegistrationConfirmationCommand(email)),
        return_exceptions=True,
    ), timeout=10)
    # Either confirmation wins, or resend invalidates the old challenge first.
    assert results[1] is None
    assert results[0] is None or isinstance(results[0], VerificationChallengeAlreadyUsedError)
    async with session_factory() as session:
        challenges = (await session.scalars(select(SqlAlchemyVerificationChallengeModel))).all()
        assert sum(challenge.used_at is None for challenge in challenges) == (0 if results[0] is None else 1)


async def test_http_resend_replaces_link_and_returns_same_response_for_ineligible_email(
        session_factory, redis_context, monkeypatch,
):
    from backend.infrastructure.settings import Settings, get_settings
    from backend.main import app

    user_id, email, old = await seed(session_factory)
    settings = Settings(_env_file=None, database_url='postgresql+asyncpg://localhost/fincore_test')
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: settings)
    monkeypatch.setattr(app.state, 'session_factory', session_factory, raising=False)
    monkeypatch.setattr(app.state, 'rate_limiter', redis_context.limiter, raising=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/v1/auth/confirm/resend', json={'email': email.value})
        assert response.status_code == 202
        async with session_factory() as session:
            messages = (await session.scalars(select(SqlAlchemyOutboxModel).order_by(SqlAlchemyOutboxModel.created_at))).all()
            assert len(messages) == 2
            new = messages[-1].payload['token']
        assert (await client.post('/v1/auth/confirm', json={'token': old, 'password': 'Password1!'})).status_code == 400
        assert (await client.post('/v1/auth/confirm', json={'token': new, 'password': 'Password1!'})).status_code == 204
        active = await client.post('/v1/auth/confirm/resend', json={'email': email.value})
        unknown = await client.post('/v1/auth/confirm/resend', json={'email': 'missing@example.com'})
        assert active.status_code == unknown.status_code == 202
        assert active.json() == unknown.json() == response.json()
        async with session_factory() as session:
            assert len((await session.scalars(select(SqlAlchemyOutboxModel))).all()) == 2
