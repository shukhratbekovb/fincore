from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from backend.application.auth.errors import UserInactiveError
from backend.application.session.dtos.remove_session import RemoveSessionCommand
from backend.application.session.errors import SessionNotFoundError
from backend.application.session.use_cases.remove_session import RemoveSessionUseCase
from backend.application.user.errors import UserNotFoundError
from backend.domain.session.entities import Session
from backend.domain.user.entities import User
from backend.domain.user.value_objects import Email, HashedPassword, Username


@pytest.fixture
def context(now):
    user = User.created_by_admin(Username('alice'), Email('alice@example.com'), HashedPassword('test-hash'))
    session = Session.create(user_id=user.id, ip_address='127.0.0.1', now=now, ttl=timedelta(days=1))
    uow = AsyncMock()
    uow.users.get_by_id_for_update.return_value = user
    uow.sessions.get_by_id_for_update.return_value = session
    clock = Mock()
    clock.now.return_value = now
    return SimpleNamespace(
        user=user, session=session, uow=uow, clock=clock,
        command=RemoveSessionCommand(user_id=user.id, session_id=session.id),
        use_case=RemoveSessionUseCase(uow=uow, clock=clock),
    )


async def test_revocation_uses_time_after_lock_wait_and_preserves_lock_order(context, now):
    ctx = context
    # A concurrent refresh records activity while this operation waits for locks.
    activity_time = now + timedelta(minutes=2)
    revoke_time = activity_time + timedelta(seconds=1)
    operations = []

    async def lock_user(user_id):
        operations.append('user')
        return ctx.user

    async def lock_session(session_id):
        operations.append('session')
        ctx.session.record_activity(now=activity_time, ip_address='127.0.0.2', user_agent='Browser')
        ctx.clock.now.return_value = revoke_time
        return ctx.session

    ctx.uow.users.get_by_id_for_update.side_effect = lock_user
    ctx.uow.sessions.get_by_id_for_update.side_effect = lock_session
    await ctx.use_case.execute(ctx.command)

    assert operations == ['user', 'session']
    ctx.uow.users.get_by_id_for_update.assert_awaited_once_with(ctx.user.id)
    ctx.uow.sessions.get_by_id_for_update.assert_awaited_once_with(ctx.session.id)
    ctx.clock.now.assert_called_once_with()
    assert ctx.session.revoked_at == ctx.session.updated_at == revoke_time
    assert ctx.session.last_used_at == activity_time
    assert ctx.session.last_ip_address == '127.0.0.2'
    ctx.uow.sessions.save.assert_awaited_once_with(ctx.session)
    ctx.uow.commit.assert_awaited_once()


@pytest.mark.parametrize('problem', ['missing', 'foreign', 'foreign_revoked'])
async def test_missing_and_foreign_sessions_raise_same_error_without_modification(context, now, problem):
    ctx = context
    if problem == 'missing':
        ctx.uow.sessions.get_by_id_for_update.return_value = None
    else:
        ctx.session.user_id = uuid4()
        if problem == 'foreign_revoked':
            ctx.session.revoke(now=now - timedelta(minutes=1))
    previous_revocation = ctx.session.revoked_at

    with pytest.raises(SessionNotFoundError):
        await ctx.use_case.execute(ctx.command)

    assert ctx.session.revoked_at == previous_revocation
    ctx.clock.now.assert_not_called()
    ctx.uow.sessions.save.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()


@pytest.mark.parametrize('problem', ['missing', 'inactive'])
async def test_ineligible_user_is_rejected_before_loading_session(context, problem):
    ctx = context
    if problem == 'missing':
        ctx.uow.users.get_by_id_for_update.return_value = None
    else:
        ctx.user.suspend()

    with pytest.raises(UserNotFoundError if problem == 'missing' else UserInactiveError):
        await ctx.use_case.execute(ctx.command)

    ctx.uow.sessions.get_by_id_for_update.assert_not_awaited()
    ctx.uow.sessions.save.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()
    ctx.clock.now.assert_not_called()


async def test_repeated_revocation_preserves_original_time_without_writing_again(context, now):
    ctx = context
    await ctx.use_case.execute(ctx.command)
    ctx.uow.sessions.save.reset_mock()
    ctx.uow.commit.reset_mock()
    ctx.clock.now.reset_mock()
    ctx.clock.now.return_value = now + timedelta(minutes=1)

    await ctx.use_case.execute(ctx.command)

    assert ctx.session.revoked_at == ctx.session.updated_at == now
    ctx.uow.sessions.save.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()
    ctx.clock.now.assert_not_called()


@pytest.mark.parametrize('stage', ['save', 'commit'])
async def test_storage_failure_propagates_to_uow_for_rollback(context, stage):
    ctx = context
    operation = ctx.uow.sessions.save if stage == 'save' else ctx.uow.commit
    operation.side_effect = RuntimeError('storage unavailable')

    with pytest.raises(RuntimeError, match='storage unavailable'):
        await ctx.use_case.execute(ctx.command)

    assert ctx.uow.__aexit__.call_args.args[0] is RuntimeError
    if stage == 'save':
        ctx.uow.commit.assert_not_awaited()
