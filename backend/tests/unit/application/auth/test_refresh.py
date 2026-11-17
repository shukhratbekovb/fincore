import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from backend.application.auth.dtos.refresh import RefreshSessionCommand
from backend.application.auth.use_cases.refresh import RefreshSessionUseCase
from backend.application.auth.errors import UserInactiveError
from backend.domain.session.entities import Session, RefreshToken
from backend.domain.session.errors import InvalidRefreshTokenError, RefreshTokenReuseError
from backend.domain.user.entities import User
from backend.domain.user.value_objects import Username, Email


class RefreshTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 3, tzinfo=timezone.utc)
        self.user = User.register(Username('alice'), Email('alice@example.com'))
        self.user.activate()
        self.session = Session.create(user_id=self.user.id, ip_address='old-ip', now=self.now, ttl=timedelta(days=1))
        self.token = RefreshToken(session_id=self.session.id, token_hash='old-hash', expires_at=self.session.expires_at)
        self.uow = AsyncMock()
        self.uow.sessions.get_by_id.return_value = self.session
        self.uow.sessions.get_by_id_for_update.return_value = self.session
        self.uow.refresh_tokens.get_by_token_hash.return_value = self.token
        self.uow.refresh_tokens.get_by_id_for_update.return_value = self.token
        self.uow.users.get_by_id_for_update.return_value = self.user
        self.issuer = Mock()
        self.issuer.encode.return_value = 'access'
        self.use_case = RefreshSessionUseCase(
            self.uow, self.issuer, SimpleNamespace(generate=lambda: 'new-secret'),
            SimpleNamespace(hash=lambda raw: 'old-hash' if raw == 'old-secret' else 'new-hash'),
            SimpleNamespace(now=lambda: self.now), timedelta(days=30),
        )
        self.cmd = RefreshSessionCommand(refresh_token='old-secret', ip_address='new-ip', user_agent='browser')

    async def test_rotation_preserves_session_and_absolute_expiry(self):
        result = await self.use_case.execute(self.cmd)
        replacement = self.uow.refresh_tokens.add.call_args.args[0]
        self.assertEqual(replacement.session_id, self.session.id)
        self.assertEqual(replacement.expires_at, self.session.expires_at)
        self.assertEqual(self.token.replaced_by_id, replacement.id)
        self.assertEqual(self.token.used_at, self.now)
        self.assertEqual(self.session.ip_address, 'old-ip')
        self.assertEqual(self.session.last_ip_address, 'new-ip')
        self.assertEqual(result.refresh_token, 'new-secret')
        self.uow.sessions.add.assert_not_awaited()
        self.uow.commit.assert_awaited_once()
        self.assertNotIn('new-hash', repr(replacement))

    async def test_reuse_commits_revocation_before_error(self):
        self.token.used_at = self.now
        with self.assertRaises(RefreshTokenReuseError):
            await self.use_case.execute(self.cmd)
        self.assertEqual(self.session.revoked_at, self.now)
        self.uow.commit.assert_awaited_once()
        self.uow.refresh_tokens.add.assert_not_awaited()
        self.issuer.encode.assert_not_called()
        self.assertIsNone(self.uow.__aexit__.call_args.args[0])

    async def test_invalid_states_do_not_commit(self):
        for case in ('missing', 'expired_token', 'expired_session', 'revoked', 'missing_user', 'inactive'):
            with self.subTest(case=case):
                self.setUp()
                error = InvalidRefreshTokenError
                if case == 'missing':
                    self.uow.refresh_tokens.get_by_token_hash.return_value = None
                elif case == 'expired_token':
                    self.token.expires_at = self.now
                elif case == 'expired_session':
                    self.session.expires_at = self.now
                elif case == 'revoked':
                    self.session.revoke(now=self.now)
                elif case == 'missing_user':
                    self.uow.users.get_by_id_for_update.return_value = None
                else:
                    self.user.suspend()
                    error = UserInactiveError
                with self.assertRaises(error):
                    await self.use_case.execute(self.cmd)
                self.uow.commit.assert_not_awaited()
                self.uow.refresh_tokens.add.assert_not_awaited()

    async def test_storage_failure_does_not_commit(self):
        self.uow.refresh_tokens.add.side_effect = RuntimeError('storage failure')
        with self.assertRaises(RuntimeError):
            await self.use_case.execute(self.cmd)
        self.uow.commit.assert_not_awaited()

    def test_invalid_ttl(self):
        with self.assertRaises(ValueError):
            RefreshSessionUseCase(self.uow, self.issuer, Mock(), Mock(), Mock(), timedelta(0))
