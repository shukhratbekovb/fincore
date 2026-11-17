from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.application.auth.dtos.login import LoginUserCommand
from backend.application.auth.errors import InvalidCredentialsError, UserInactiveError
from backend.application.auth.use_cases.login import LoginUserUseCase
from backend.domain.user.entities import User
from backend.domain.user.value_objects import Email, HashedPassword, RawPassword, Username


@pytest.fixture
def login_context(now):
    user = User.created_by_admin(Username('alice'), Email('alice@example.com'), HashedPassword('digest'))
    uow = AsyncMock()
    uow.users = SimpleNamespace(get_by_username=AsyncMock(return_value=user),
                                get_by_id_for_update=AsyncMock(return_value=user), save=AsyncMock())
    uow.sessions = SimpleNamespace(add=AsyncMock())
    uow.refresh_tokens = SimpleNamespace(add=AsyncMock())
    password_hasher = Mock()
    password_hasher.verify.return_value = True
    issuer = Mock()
    issuer.encode.return_value = 'access-token'
    generator = Mock()
    generator.generate.return_value = 'refresh-secret'
    hasher = Mock()
    hasher.hash.return_value = 'refresh-digest'
    use_case = LoginUserUseCase(uow, password_hasher, issuer, generator, hasher,
                               SimpleNamespace(now=lambda: now), timedelta(days=7))
    cmd = LoginUserCommand(Username('alice'), RawPassword('Password1!'), '127.0.0.1', 'Test browser')
    return SimpleNamespace(user=user, uow=uow, password_hasher=password_hasher,
                           issuer=issuer, generator=generator, hasher=hasher, use_case=use_case, cmd=cmd)


async def test_login_creates_linked_session_and_token(login_context, now):
    ctx = login_context
    result = await ctx.use_case.execute(ctx.cmd)
    session = ctx.uow.sessions.add.call_args.args[0]
    token = ctx.uow.refresh_tokens.add.call_args.args[0]
    assert session.user_id == ctx.user.id
    assert session.ip_address == ctx.cmd.ip_address
    assert session.user_agent == ctx.cmd.user_agent
    assert session.created_at == now
    assert session.expires_at == now + timedelta(days=7)
    assert token.session_id == session.id
    assert token.token_hash == 'refresh-digest'
    assert token.expires_at == session.expires_at
    assert ctx.user.last_login_at is not None
    assert result.access_token == 'access-token'
    assert result.refresh_token == 'refresh-secret'
    ctx.uow.users.get_by_id_for_update.assert_awaited_once_with(ctx.user.id)
    ctx.password_hasher.verify.assert_called_once_with(ctx.cmd.password, ctx.user.password_hash)
    ctx.uow.users.save.assert_awaited_once_with(ctx.user)
    ctx.uow.commit.assert_awaited_once()


@pytest.mark.parametrize('reason', ['missing', 'deleted_after_lookup', 'no_password', 'wrong_password', 'suspended', 'closed'])
async def test_login_rejects_without_creating_session(login_context, reason):
    ctx = login_context
    expected = InvalidCredentialsError
    if reason == 'missing':
        ctx.uow.users.get_by_username.return_value = None
    elif reason == 'deleted_after_lookup':
        ctx.uow.users.get_by_id_for_update.return_value = None
    elif reason == 'no_password':
        ctx.user.password_hash = None
    elif reason == 'wrong_password':
        ctx.password_hasher.verify.return_value = False
    else:
        ctx.user.suspend() if reason == 'suspended' else ctx.user.close()
        expected = UserInactiveError
    with pytest.raises(expected):
        await ctx.use_case.execute(ctx.cmd)
    ctx.uow.sessions.add.assert_not_awaited()
    ctx.uow.refresh_tokens.add.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()
    ctx.issuer.encode.assert_not_called()
    if reason in {'missing', 'deleted_after_lookup', 'no_password'}:
        ctx.password_hasher.verify.assert_not_called()


@pytest.mark.parametrize('stage', ['session', 'token', 'user', 'commit'])
async def test_storage_failure_propagates_and_does_not_return_tokens(login_context, stage):
    ctx = login_context
    operation = {'session': ctx.uow.sessions.add, 'token': ctx.uow.refresh_tokens.add,
                 'user': ctx.uow.users.save, 'commit': ctx.uow.commit}[stage]
    operation.side_effect = RuntimeError('storage unavailable')
    with pytest.raises(RuntimeError, match='storage unavailable'):
        await ctx.use_case.execute(ctx.cmd)
    assert ctx.uow.__aexit__.call_args.args[0] is RuntimeError
    if stage != 'commit':
        ctx.uow.commit.assert_not_awaited()


@pytest.mark.parametrize('ttl', [timedelta(0), timedelta(seconds=-1)])
def test_login_rejects_invalid_ttl(login_context, ttl):
    ctx = login_context
    with pytest.raises(ValueError):
        LoginUserUseCase(ctx.uow, ctx.password_hasher, ctx.issuer, ctx.generator,
                         ctx.hasher, ctx.use_case.clock, ttl)
