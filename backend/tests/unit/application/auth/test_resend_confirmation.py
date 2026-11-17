from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.application.auth.dtos.resend_confirmation import ResendRegistrationConfirmationCommand
from backend.application.auth.use_cases.resend_confirmation import ResendRegistrationConfirmationUseCase
from backend.domain.user.entities import User
from backend.domain.user.enums import UserStatusEnum
from backend.domain.user.value_objects import Email, Username
from backend.domain.verification.enums import VerificationPurpose


@pytest.fixture
def context():
    user = User.register(Username('alice'), Email('alice@example.com'))
    uow = AsyncMock()
    uow.users = SimpleNamespace(
        get_by_email=AsyncMock(return_value=user), get_by_id_for_update=AsyncMock(return_value=user),
    )
    uow.verification_challenges = SimpleNamespace(add=AsyncMock(), invalidate_unused_by_user_id=AsyncMock())
    uow.outbox = SimpleNamespace(add=AsyncMock())
    now = datetime(2026, 11, 15, tzinfo=timezone.utc)
    generator = Mock()
    generator.generate.return_value = 'secret'
    hasher = Mock()
    hasher.hash.return_value = 'digest'
    case = ResendRegistrationConfirmationUseCase(
        uow, generator, hasher, SimpleNamespace(now=lambda: now), timedelta(hours=1),
    )
    return SimpleNamespace(user=user, uow=uow, now=now, case=case,
                           command=ResendRegistrationConfirmationCommand(user.email))


async def test_pending_account_gets_replacement_link_in_one_transaction(context):
    ctx = context
    order = []
    for label, method in [
        ('lock', ctx.uow.users.get_by_id_for_update),
        ('invalidate', ctx.uow.verification_challenges.invalidate_unused_by_user_id),
        ('challenge', ctx.uow.verification_challenges.add),
        ('outbox', ctx.uow.outbox.add), ('commit', ctx.uow.commit),
    ]:
        method.side_effect = lambda *args, label=label, **kwargs: order.append(label) or (ctx.user if label == 'lock' else None)
    await ctx.case.execute(ctx.command)
    assert order == ['lock', 'invalidate', 'challenge', 'outbox', 'commit']
    ctx.uow.verification_challenges.invalidate_unused_by_user_id.assert_awaited_once_with(
        ctx.user.id, purpose=VerificationPurpose.REGISTRATION, now=ctx.now,
    )
    challenge = ctx.uow.verification_challenges.add.call_args.args[0]
    assert challenge.user_id == ctx.user.id
    assert challenge.token_hash == 'digest'
    assert challenge.expires_at == ctx.now + timedelta(hours=1)
    assert challenge.purpose == VerificationPurpose.REGISTRATION
    message = ctx.uow.outbox.add.call_args.args[0]
    assert message.token == 'secret'
    assert message.expires_at == challenge.expires_at
    assert message.email == ctx.user.email
    assert 'secret' not in repr(message)


@pytest.mark.parametrize('status', [UserStatusEnum.ACTIVE, UserStatusEnum.SUSPENDED, UserStatusEnum.CLOSED, None])
async def test_ineligible_accounts_do_not_change_data(context, status):
    ctx = context
    if status is None:
        ctx.uow.users.get_by_email.return_value = None
    else:
        ctx.user.status = status
    await ctx.case.execute(ctx.command)
    ctx.case.token_generator.generate.assert_called_once()
    ctx.case.token_hasher.hash.assert_called_once_with('secret')
    ctx.uow.verification_challenges.invalidate_unused_by_user_id.assert_not_awaited()
    ctx.uow.verification_challenges.add.assert_not_awaited()
    ctx.uow.outbox.add.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()


@pytest.mark.parametrize('missing', [True, False])
async def test_user_is_rechecked_under_lock(context, missing):
    ctx = context
    if missing:
        ctx.uow.users.get_by_id_for_update.return_value = None
    else:
        replacement = User.register(Username('alice'), Email('changed@example.com'))
        ctx.uow.users.get_by_id_for_update.return_value = replacement
    await ctx.case.execute(ctx.command)
    ctx.uow.outbox.add.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()


async def test_outbox_failure_prevents_commit(context):
    ctx = context
    ctx.uow.outbox.add.side_effect = RuntimeError('outbox unavailable')
    with pytest.raises(RuntimeError):
        await ctx.case.execute(ctx.command)
    ctx.uow.commit.assert_not_awaited()
    assert ctx.uow.__aexit__.call_args.args[0] is RuntimeError


@pytest.mark.parametrize('ttl', [timedelta(0), timedelta(seconds=-1)])
def test_positive_ttl_required(context, ttl):
    with pytest.raises(ValueError):
        ResendRegistrationConfirmationUseCase(
            context.uow, context.case.token_generator, context.case.token_hasher, context.case.clock, ttl,
        )
