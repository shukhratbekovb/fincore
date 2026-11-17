from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from backend.application.auth.dtos.password_reset import (
    ConfirmPasswordResetCommand, ConfirmPasswordResetResult, RequestPasswordResetCommand,
)
from backend.application.auth.errors import InvalidPasswordResetTokenError
from backend.application.auth.use_cases.confirm_password_reset import ConfirmPasswordResetUseCase
from backend.application.auth.use_cases.request_password_reset import RequestPasswordResetUseCase
from backend.application.notifications.messages import SendPasswordChangedNotification
from backend.application.verification.messages import SendPasswordResetConfirmation
from backend.domain.user.entities import User
from backend.domain.user.enums import UserStatusEnum
from backend.domain.user.value_objects import Email, HashedPassword, RawPassword, Username
from backend.domain.verification.entities import VerificationChallenge
from backend.domain.verification.enums import VerificationPurpose


@pytest.fixture
def context(now):
    user = User.created_by_admin(Username('alice'), Email('alice@example.com'), HashedPassword('old-digest'))
    challenge = VerificationChallenge(user_id=user.id, purpose=VerificationPurpose.PASSWORD_RESET,
                                      token_hash='token-digest', expires_at=now + timedelta(minutes=15))
    uow = AsyncMock()
    uow.users = SimpleNamespace(
        get_by_email=AsyncMock(return_value=user), get_by_id_for_update=AsyncMock(return_value=user), save=AsyncMock(),
    )
    uow.verification_challenges = SimpleNamespace(
        add=AsyncMock(), get_by_token_hash=AsyncMock(return_value=challenge),
        get_by_token_hash_for_update=AsyncMock(return_value=challenge), save=AsyncMock(),
        invalidate_unused_by_user_id=AsyncMock(),
    )
    uow.sessions = SimpleNamespace(revoke_all_by_user_id=AsyncMock())
    uow.outbox = SimpleNamespace(add=AsyncMock())
    token_generator = Mock()
    token_generator.generate.return_value = 'reset-secret'
    token_hasher = Mock()
    token_hasher.hash.return_value = 'token-digest'
    password_generator = Mock()
    password_generator.generate.return_value = RawPassword('GeneratedPassword1!')
    password_hasher = Mock()
    password_hasher.hash.return_value = HashedPassword('new-digest')
    clock = SimpleNamespace(now=lambda: now)
    request = RequestPasswordResetUseCase(uow, token_generator, token_hasher, clock, timedelta(minutes=15))
    confirm = ConfirmPasswordResetUseCase(uow, password_generator, password_hasher, token_hasher, clock)
    return SimpleNamespace(user=user, challenge=challenge, uow=uow, token_generator=token_generator,
                           token_hasher=token_hasher, password_generator=password_generator,
                           password_hasher=password_hasher, clock=clock, request=request, confirm=confirm)


async def test_request_stores_reset_challenge_and_link_without_changing_credentials(context, now):
    ctx = context
    result = await ctx.request.execute(RequestPasswordResetCommand(ctx.user.email))
    assert result is None
    ctx.uow.users.get_by_email.assert_awaited_once_with(ctx.user.email)
    ctx.uow.users.get_by_id_for_update.assert_awaited_once_with(ctx.user.id)
    challenge = ctx.uow.verification_challenges.add.call_args.args[0]
    message = ctx.uow.outbox.add.call_args.args[0]
    assert challenge.purpose == VerificationPurpose.PASSWORD_RESET
    assert challenge.user_id == ctx.user.id and challenge.token_hash == 'token-digest'
    assert challenge.expires_at == now + timedelta(minutes=15)
    assert isinstance(message, SendPasswordResetConfirmation)
    assert message.user_id == ctx.user.id and message.email == ctx.user.email
    assert message.token == 'reset-secret' and message.expires_at == challenge.expires_at
    assert ctx.user.password_hash == HashedPassword('old-digest')
    ctx.password_generator.generate.assert_not_called()
    ctx.password_hasher.hash.assert_not_called()
    ctx.uow.users.save.assert_not_awaited()
    ctx.uow.sessions.revoke_all_by_user_id.assert_not_awaited()
    ctx.uow.verification_challenges.invalidate_unused_by_user_id.assert_not_awaited()
    ctx.uow.commit.assert_awaited_once()


@pytest.mark.parametrize('reason', ['unknown', 'deleted', 'changed_email', 'suspended', 'closed', 'pending', 'no_password'])
async def test_request_does_not_disclose_unknown_or_ineligible_accounts(context, reason):
    ctx = context
    email = ctx.user.email
    if reason == 'unknown':
        ctx.uow.users.get_by_email.return_value = None
    elif reason == 'deleted':
        ctx.uow.users.get_by_id_for_update.return_value = None
    elif reason == 'changed_email':
        ctx.uow.users.get_by_id_for_update.return_value = replace(ctx.user, email=Email('other@example.com'))
    elif reason == 'no_password':
        ctx.user.password_hash = None
    else:
        ctx.user.status = {'suspended': UserStatusEnum.SUSPENDED, 'closed': UserStatusEnum.CLOSED,
                           'pending': UserStatusEnum.PENDING_CONFIRMATION}[reason]
    assert await ctx.request.execute(RequestPasswordResetCommand(email)) is None
    ctx.token_generator.generate.assert_called_once()
    ctx.token_hasher.hash.assert_called_once_with('reset-secret')
    ctx.uow.verification_challenges.add.assert_not_awaited()
    ctx.uow.outbox.add.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()


@pytest.mark.parametrize('stage', ['challenge', 'outbox', 'commit'])
async def test_request_storage_failure_propagates(context, stage):
    ctx = context
    operation = {'challenge': ctx.uow.verification_challenges.add, 'outbox': ctx.uow.outbox.add,
                 'commit': ctx.uow.commit}[stage]
    operation.side_effect = RuntimeError('storage unavailable')
    with pytest.raises(RuntimeError):
        await ctx.request.execute(RequestPasswordResetCommand(ctx.user.email))
    if stage != 'commit':
        ctx.uow.commit.assert_not_awaited()
    assert ctx.uow.__aexit__.call_args.args[0] is RuntimeError
    assert ctx.user.password_hash == HashedPassword('old-digest')


@pytest.mark.parametrize('ttl', [timedelta(0), timedelta(seconds=-1)])
def test_request_requires_positive_ttl(context, ttl):
    with pytest.raises(ValueError):
        replace(context.request, reset_ttl=ttl)


async def test_confirm_generates_once_and_commits_all_changes_before_releasing_password(context, now):
    ctx = context
    operations = Mock()
    operations.attach_mock(ctx.uow.verification_challenges.get_by_token_hash, 'read_identity')
    operations.attach_mock(ctx.uow.users.get_by_id_for_update, 'lock_user')
    operations.attach_mock(ctx.uow.verification_challenges.get_by_token_hash_for_update, 'lock_challenge')
    operations.attach_mock(ctx.password_generator.generate, 'generate')
    operations.attach_mock(ctx.uow.users.save, 'save_user')
    operations.attach_mock(ctx.uow.verification_challenges.save, 'save_challenge')
    operations.attach_mock(ctx.uow.sessions.revoke_all_by_user_id, 'revoke_sessions')
    operations.attach_mock(ctx.uow.verification_challenges.invalidate_unused_by_user_id, 'invalidate_resets')
    operations.attach_mock(ctx.uow.outbox.add, 'outbox')
    operations.attach_mock(ctx.uow.commit, 'commit')
    operations.attach_mock(ctx.uow.__aexit__, 'exit')
    result = await ctx.confirm.execute(ConfirmPasswordResetCommand('reset-secret'))
    assert isinstance(result, ConfirmPasswordResetResult) and result.password == 'GeneratedPassword1!'
    assert [call[0] for call in operations.mock_calls] == [
        'read_identity', 'lock_user', 'lock_challenge', 'generate', 'save_user', 'save_challenge',
        'revoke_sessions', 'invalidate_resets', 'outbox', 'commit', 'exit',
    ]
    ctx.password_hasher.hash.assert_called_once_with(ctx.password_generator.generate.return_value)
    assert ctx.user.password_hash == HashedPassword('new-digest')
    assert ctx.challenge.used_at == now
    ctx.uow.sessions.revoke_all_by_user_id.assert_awaited_once_with(ctx.user.id, now=now)
    ctx.uow.verification_challenges.invalidate_unused_by_user_id.assert_awaited_once_with(
        ctx.user.id, purpose=VerificationPurpose.PASSWORD_RESET, now=now,
    )
    notification = ctx.uow.outbox.add.call_args.args[0]
    assert isinstance(notification, SendPasswordChangedNotification)
    assert notification.user_id == ctx.user.id and notification.email == ctx.user.email
    assert notification.changed_at == now
    assert not hasattr(notification, 'password')
    assert result.password not in repr(notification)
    assert result.password not in repr(result)


@pytest.mark.parametrize('reason', [
    'unknown', 'wrong_purpose', 'deleted_user', 'inactive', 'no_password',
    'deleted_challenge', 'changed_identity', 'changed_owner', 'changed_hash',
    'expired', 'used', 'fresh_state_used', 'fresh_state_purpose',
])
async def test_invalid_reset_never_generates_or_saves_a_password(context, now, reason):
    ctx = context
    repo = ctx.uow.verification_challenges
    if reason == 'unknown':
        repo.get_by_token_hash.return_value = None
    elif reason == 'wrong_purpose':
        ctx.challenge.purpose = VerificationPurpose.REGISTRATION
    elif reason == 'deleted_user':
        ctx.uow.users.get_by_id_for_update.return_value = None
    elif reason == 'inactive':
        ctx.user.suspend()
    elif reason == 'no_password':
        ctx.user.password_hash = None
    elif reason == 'deleted_challenge':
        repo.get_by_token_hash_for_update.return_value = None
    elif reason in {'changed_identity', 'changed_owner', 'changed_hash'}:
        field = {'changed_identity': 'id', 'changed_owner': 'user_id', 'changed_hash': 'token_hash'}[reason]
        value = 'different-digest' if reason == 'changed_hash' else uuid4()
        repo.get_by_token_hash_for_update.return_value = replace(ctx.challenge, **{field: value})
    elif reason == 'expired':
        ctx.challenge.expires_at = now
    elif reason == 'used':
        ctx.challenge.used_at = now
    elif reason == 'fresh_state_used':
        repo.get_by_token_hash_for_update.return_value = replace(ctx.challenge, used_at=now)
    else:
        repo.get_by_token_hash_for_update.return_value = replace(ctx.challenge, purpose=VerificationPurpose.REGISTRATION)
    with pytest.raises(InvalidPasswordResetTokenError):
        await ctx.confirm.execute(ConfirmPasswordResetCommand('reset-secret'))
    ctx.password_generator.generate.assert_not_called()
    ctx.password_hasher.hash.assert_not_called()
    ctx.uow.users.save.assert_not_awaited()
    ctx.uow.sessions.revoke_all_by_user_id.assert_not_awaited()
    repo.invalidate_unused_by_user_id.assert_not_awaited()
    ctx.uow.outbox.add.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()
    if reason in {'unknown', 'wrong_purpose'}:
        ctx.uow.users.get_by_id_for_update.assert_not_awaited()


@pytest.mark.parametrize('token', ['', ' ', 'has spaces', 'x' * 513, None, 123])
async def test_malformed_reset_token_is_rejected_before_transaction(context, token):
    with pytest.raises(InvalidPasswordResetTokenError):
        await context.confirm.execute(ConfirmPasswordResetCommand(token))
    context.token_hasher.hash.assert_not_called()
    context.uow.__aenter__.assert_not_awaited()


@pytest.mark.parametrize('stage', ['generator', 'hasher', 'user', 'challenge', 'sessions', 'invalidate', 'outbox', 'commit', 'exit'])
async def test_confirm_does_not_return_password_if_any_stage_fails(context, stage):
    ctx = context
    operation = {
        'generator': ctx.password_generator.generate, 'hasher': ctx.password_hasher.hash,
        'user': ctx.uow.users.save, 'challenge': ctx.uow.verification_challenges.save,
        'sessions': ctx.uow.sessions.revoke_all_by_user_id,
        'invalidate': ctx.uow.verification_challenges.invalidate_unused_by_user_id,
        'outbox': ctx.uow.outbox.add, 'commit': ctx.uow.commit, 'exit': ctx.uow.__aexit__,
    }[stage]
    operation.side_effect = RuntimeError('storage unavailable')
    with pytest.raises(RuntimeError):
        await ctx.confirm.execute(ConfirmPasswordResetCommand('reset-secret'))
    if stage not in {'commit', 'exit'}:
        ctx.uow.commit.assert_not_awaited()
    if stage != 'exit':
        assert ctx.uow.__aexit__.call_args.args[0] is RuntimeError


async def test_reused_confirmation_does_not_generate_another_password(context):
    await context.confirm.execute(ConfirmPasswordResetCommand('reset-secret'))
    context.password_generator.generate.reset_mock()
    with pytest.raises(InvalidPasswordResetTokenError):
        await context.confirm.execute(ConfirmPasswordResetCommand('reset-secret'))
    context.password_generator.generate.assert_not_called()


def test_reset_secret_dtos_and_outbox_message_hide_tokens(context):
    command = ConfirmPasswordResetCommand('reset-secret')
    message = SendPasswordResetConfirmation(user_id=context.user.id, email=context.user.email,
                                           token='reset-secret', expires_at=context.challenge.expires_at)
    assert 'reset-secret' not in repr(command)
    assert 'reset-secret' not in repr(message)
