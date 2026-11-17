import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from backend.application.auth.dtos.change_password import ChangePasswordCommand
from backend.application.auth.dtos.logout import LogoutUserCommand
from backend.application.auth.errors import InvalidCredentialsError, UserInactiveError
from backend.application.auth.use_cases.change_password import ChangePasswordUseCase
from backend.application.auth.use_cases.logout import LogoutUserUseCase
from backend.domain.session.entities import Session, RefreshToken
from backend.domain.user.entities import User
from backend.domain.user.value_objects import Email, Username, RawPassword, HashedPassword


class PasswordLogoutTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 3, tzinfo=timezone.utc)
        self.clock = SimpleNamespace(now=lambda: self.now)
        self.user = User.created_by_admin(Username('alice'), Email('alice@example.com'), HashedPassword('old-hash'))
        self.session = Session.create(user_id=self.user.id, ip_address='127.0.0.1', now=self.now, ttl=timedelta(days=1))
        self.token = RefreshToken(session_id=self.session.id, token_hash='digest', expires_at=self.session.expires_at)
        self.uow = AsyncMock()
        self.uow.users.get_by_id_for_update.return_value = self.user
        self.uow.sessions.get_by_id_for_update.return_value = self.session
        self.uow.refresh_tokens.get_by_token_hash.return_value = self.token
        self.hasher = Mock()
        self.hasher.verify.return_value = True
        self.hasher.hash.return_value = HashedPassword('new-hash')
        self.change = ChangePasswordUseCase(self.uow, self.hasher, self.clock)
        self.cmd = ChangePasswordCommand(self.user.id, RawPassword('OldPassword1!'), RawPassword('NewPassword1!'))
        self.logout = LogoutUserUseCase(self.uow, SimpleNamespace(hash=lambda token: 'digest'), self.clock)

    async def test_password_change_saves_and_revokes_before_commit(self):
        order = []
        for label, method in [('save', self.uow.users.save), ('revoke', self.uow.sessions.revoke_all_by_user_id), ('commit', self.uow.commit)]:
            method.side_effect = lambda *args, label=label, **kwargs: order.append(label)
        await self.change.execute(self.cmd)
        self.assertEqual(self.user.password_hash, HashedPassword('new-hash'))
        self.uow.sessions.revoke_all_by_user_id.assert_awaited_once_with(self.user.id, now=self.now)
        self.assertEqual(order, ['save', 'revoke', 'commit'])

    async def test_password_change_rejections(self):
        for case in ('missing', 'no_password', 'wrong_password', 'inactive'):
            with self.subTest(case=case):
                self.setUp()
                if case == 'missing':
                    self.uow.users.get_by_id_for_update.return_value = None
                elif case == 'no_password':
                    self.user.password_hash = None
                elif case == 'wrong_password':
                    self.hasher.verify.return_value = False
                else:
                    self.user.suspend()
                error = UserInactiveError if case == 'inactive' else InvalidCredentialsError
                with self.assertRaises(error):
                    await self.change.execute(self.cmd)
                self.uow.commit.assert_not_awaited()
                self.uow.sessions.revoke_all_by_user_id.assert_not_awaited()
                self.hasher.hash.assert_not_called()

    async def test_revocation_failure_prevents_password_commit(self):
        self.uow.sessions.revoke_all_by_user_id.side_effect = RuntimeError('failure')
        with self.assertRaises(RuntimeError):
            await self.change.execute(self.cmd)
        self.uow.commit.assert_not_awaited()
        self.assertIs(self.uow.__aexit__.call_args.args[0], RuntimeError)

    async def test_logout_with_rotated_token_revokes_session(self):
        self.token.used_at = self.now
        await self.logout.execute(LogoutUserCommand('old-token'))
        self.assertEqual(self.session.revoked_at, self.now)
        self.uow.sessions.save.assert_awaited_once_with(self.session)
        self.uow.commit.assert_awaited_once()

    async def test_logout_is_idempotent(self):
        for case in ('unknown_token', 'missing_session', 'revoked'):
            with self.subTest(case=case):
                self.setUp()
                if case == 'unknown_token':
                    self.uow.refresh_tokens.get_by_token_hash.return_value = None
                elif case == 'missing_session':
                    self.uow.sessions.get_by_id_for_update.return_value = None
                else:
                    self.session.revoke(now=self.now)
                await self.logout.execute(LogoutUserCommand('token'))
                self.uow.commit.assert_not_awaited()
                self.uow.sessions.save.assert_not_awaited()

    async def test_logout_storage_failure_prevents_commit(self):
        self.uow.sessions.save.side_effect = RuntimeError('failure')
        with self.assertRaises(RuntimeError):
            await self.logout.execute(LogoutUserCommand('token'))
        self.uow.commit.assert_not_awaited()
