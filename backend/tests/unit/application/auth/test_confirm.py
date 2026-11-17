import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from backend.application.auth.dtos.confirm import ConfirmUserCommand
from backend.application.auth.use_cases.confirm import ConfirmUserUseCase
from backend.application.user.errors import UserNotFoundError
from backend.application.verification.errors import VerificationChallengeNotFoundError
from backend.domain.user.entities import User
from backend.domain.user.enums import UserStatusEnum
from backend.domain.user.errors import UserNotPendingConfirmationError
from backend.domain.user.value_objects import Email, HashedPassword, RawPassword, Username
from backend.domain.verification.entities import VerificationChallenge
from backend.domain.verification.enums import VerificationPurpose
from backend.domain.verification.errors import (
    VerificationChallengeAlreadyUsedError,
    VerificationChallengeExpiredError,
    VerificationChallengePurposeMismatchError,
)


class ConfirmUserTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 2, tzinfo=timezone.utc)
        self.user = User.register(Username('alice'), Email('alice@example.com'))
        self.challenge = VerificationChallenge(
            user_id=self.user.id,
            purpose=VerificationPurpose.REGISTRATION,
            token_hash='digest',
            expires_at=self.now + timedelta(minutes=30),
        )
        self.uow = AsyncMock()
        self.uow.users = SimpleNamespace(
            get_by_id_for_update=AsyncMock(return_value=self.user), save=AsyncMock(),
        )
        self.uow.verification_challenges = SimpleNamespace(
            get_by_token_hash=AsyncMock(return_value=self.challenge),
            get_by_token_hash_for_update=AsyncMock(return_value=self.challenge),
            save=AsyncMock(),
        )
        self.password_hasher = Mock()
        self.password_hasher.hash.return_value = HashedPassword('password-digest')
        self.token_hasher = Mock()
        self.token_hasher.hash.return_value = 'digest'
        self.use_case = ConfirmUserUseCase(
            uow=self.uow, password_hasher=self.password_hasher,
            token_hasher=self.token_hasher,
            clock=SimpleNamespace(now=lambda: self.now),
        )
        self.command = ConfirmUserCommand(token='secret', password=RawPassword('StrongPass1!'))

    async def test_confirmation_updates_user_and_consumes_token(self):
        await self.use_case.execute(self.command)
        self.token_hasher.hash.assert_called_once_with('secret')
        self.uow.verification_challenges.get_by_token_hash_for_update.assert_awaited_once_with('digest')
        self.uow.users.get_by_id_for_update.assert_awaited_once_with(self.user.id)
        self.assertEqual(self.user.status, UserStatusEnum.ACTIVE)
        self.assertEqual(self.user.password_hash, HashedPassword('password-digest'))
        self.assertEqual(self.challenge.used_at, self.now)
        self.uow.users.save.assert_awaited_once_with(self.user)
        self.uow.verification_challenges.save.assert_awaited_once_with(self.challenge)
        self.uow.commit.assert_awaited_once()

    async def assert_rejected(self, error):
        with self.assertRaises(error):
            await self.use_case.execute(self.command)
        self.uow.users.save.assert_not_awaited()
        self.uow.verification_challenges.save.assert_not_awaited()
        self.uow.commit.assert_not_awaited()
        self.assertIs(self.uow.__aexit__.call_args.args[0], error)

    async def test_unknown_token(self):
        self.uow.verification_challenges.get_by_token_hash.return_value = None
        await self.assert_rejected(VerificationChallengeNotFoundError)
        self.uow.users.get_by_id_for_update.assert_not_awaited()

    async def test_challenge_removed_between_identity_read_and_lock(self):
        self.uow.verification_challenges.get_by_token_hash_for_update.return_value = None
        await self.assert_rejected(VerificationChallengeNotFoundError)

    async def test_locked_challenge_identity_must_match(self):
        self.uow.verification_challenges.get_by_token_hash_for_update.return_value = VerificationChallenge(
            user_id=self.user.id, purpose=VerificationPurpose.REGISTRATION,
            token_hash='digest', expires_at=self.challenge.expires_at,
        )
        await self.assert_rejected(VerificationChallengeNotFoundError)

    async def test_user_is_locked_before_challenge(self):
        operations = []
        self.uow.users.get_by_id_for_update.side_effect = lambda *args: operations.append('user') or self.user
        self.uow.verification_challenges.get_by_token_hash_for_update.side_effect = lambda *args: operations.append('challenge') or self.challenge
        await self.use_case.execute(self.command)
        self.assertEqual(operations, ['user', 'challenge'])

    async def test_missing_user(self):
        self.uow.users.get_by_id_for_update.return_value = None
        await self.assert_rejected(UserNotFoundError)

    async def test_expired_token(self):
        self.challenge.expires_at = self.now
        await self.assert_rejected(VerificationChallengeExpiredError)
        self.password_hasher.hash.assert_not_called()
        self.assertIsNone(self.user.password_hash)

    async def test_used_token(self):
        self.challenge.used_at = self.now
        await self.assert_rejected(VerificationChallengeAlreadyUsedError)
        self.password_hasher.hash.assert_not_called()

    async def test_wrong_purpose(self):
        self.challenge.purpose = VerificationPurpose.PASSWORD_RESET
        await self.assert_rejected(VerificationChallengePurposeMismatchError)
        self.password_hasher.hash.assert_not_called()
        self.uow.users.get_by_id_for_update.assert_not_awaited()

    async def test_non_pending_user(self):
        for status in (UserStatusEnum.ACTIVE, UserStatusEnum.SUSPENDED, UserStatusEnum.CLOSED):
            with self.subTest(status=status):
                self.setUp()
                self.user.status = status
                await self.assert_rejected(UserNotPendingConfirmationError)
                self.assertEqual(self.user.status, status)
                self.assertIsNone(self.user.password_hash)

    async def test_save_failure_prevents_commit(self):
        self.uow.verification_challenges.save.side_effect = RuntimeError('storage failure')
        with self.assertRaises(RuntimeError):
            await self.use_case.execute(self.command)
        self.uow.commit.assert_not_awaited()
        self.assertIs(self.uow.__aexit__.call_args.args[0], RuntimeError)
