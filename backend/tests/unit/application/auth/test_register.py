import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from backend.application.auth.dtos.register import RegisterUserCommand
from backend.application.auth.errors import EmailAlreadyExistError, UsernameAlreadyExistError
from backend.application.auth.use_cases.register import RegisterUserUseCase
from backend.domain.user.enums import UserStatusEnum
from backend.domain.user.value_objects import Email, Username
from backend.domain.verification.enums import VerificationPurpose


class RegisterUserTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.uow = AsyncMock()
        self.uow.users = SimpleNamespace(
            get_by_email=AsyncMock(return_value=None),
            get_by_username=AsyncMock(return_value=None),
            add=AsyncMock(),
        )
        self.uow.verification_challenges = SimpleNamespace(add=AsyncMock())
        self.uow.outbox = SimpleNamespace(add=AsyncMock())
        self.now = datetime(2026, 11, 2, tzinfo=timezone.utc)
        self.hasher = Mock()
        self.hasher.hash.return_value = 'token-digest'
        self.use_case = RegisterUserUseCase(
            uow=self.uow,
            token_generator=SimpleNamespace(generate=lambda: 'raw-secret'),
            token_hasher=self.hasher,
            clock=SimpleNamespace(now=lambda: self.now),
            confirmation_ttl=timedelta(minutes=30),
        )
        self.command = RegisterUserCommand(
            username=Username('alice'), email=Email('alice@example.com'),
        )

    async def test_registration_prepares_confirmation_and_email_before_commit(self):
        operations = []
        for name, method in [
            ('user', self.uow.users.add),
            ('challenge', self.uow.verification_challenges.add),
            ('outbox', self.uow.outbox.add),
            ('commit', self.uow.commit),
        ]:
            method.side_effect = lambda *args, label=name: operations.append(label)
        result = await self.use_case.execute(self.command)
        user = self.uow.users.add.call_args.args[0]
        challenge = self.uow.verification_challenges.add.call_args.args[0]
        message = self.uow.outbox.add.call_args.args[0]
        self.assertEqual(operations, ['user', 'challenge', 'outbox', 'commit'])
        self.assertEqual(user.status, UserStatusEnum.PENDING_CONFIRMATION)
        self.assertIsNone(user.password_hash)
        self.assertEqual(result.user_id, user.id)
        self.assertEqual(challenge.user_id, user.id)
        self.assertEqual(challenge.purpose, VerificationPurpose.REGISTRATION)
        self.assertEqual(challenge.token_hash, 'token-digest')
        self.assertEqual(challenge.expires_at, self.now + timedelta(minutes=30))
        self.assertEqual(message.user_id, user.id)
        self.assertEqual(message.email, user.email)
        self.assertEqual(message.token, 'raw-secret')
        self.assertEqual(message.expires_at, challenge.expires_at)
        self.assertNotIn('raw-secret', repr(message))
        self.hasher.hash.assert_called_once_with('raw-secret')

    async def test_duplicate_email_stops_registration(self):
        self.uow.users.get_by_email.return_value = object()
        with self.assertRaises(EmailAlreadyExistError):
            await self.use_case.execute(self.command)
        self.uow.users.add.assert_not_awaited()
        self.uow.outbox.add.assert_not_awaited()
        self.uow.commit.assert_not_awaited()

    async def test_duplicate_username_stops_registration(self):
        self.uow.users.get_by_username.return_value = object()
        with self.assertRaises(UsernameAlreadyExistError):
            await self.use_case.execute(self.command)
        self.uow.users.add.assert_not_awaited()
        self.uow.commit.assert_not_awaited()

    async def test_outbox_failure_exits_transaction_without_commit(self):
        self.uow.outbox.add.side_effect = RuntimeError('storage unavailable')
        with self.assertRaises(RuntimeError):
            await self.use_case.execute(self.command)
        self.uow.commit.assert_not_awaited()
        self.assertIs(self.uow.__aexit__.call_args.args[0], RuntimeError)

    def test_invalid_ttl_is_rejected(self):
        for ttl in (timedelta(0), timedelta(seconds=-1)):
            with self.assertRaises(ValueError):
                RegisterUserUseCase(
                    uow=self.uow,
                    token_generator=self.use_case.token_generator,
                    token_hasher=self.hasher,
                    clock=self.use_case.clock,
                    confirmation_ttl=ttl,
                )
