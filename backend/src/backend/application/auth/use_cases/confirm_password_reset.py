from dataclasses import dataclass

from backend.application.auth.dtos.password_reset import ConfirmPasswordResetCommand, ConfirmPasswordResetResult
from backend.application.auth.errors import InvalidPasswordResetTokenError
from backend.application.auth.interfaces.password_generator import IPasswordGenerator
from backend.application.auth.interfaces.password_hasher import IPasswordHasher
from backend.application.notifications.messages import SendPasswordChangedNotification
from backend.application.share.interfaces.clock import IClock
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.verification.interfaces.token_hasher import ITokenHasher
from backend.domain.verification.enums import VerificationPurpose
from backend.domain.verification.errors import (
    VerificationChallengeAlreadyUsedError,
    VerificationChallengeExpiredError,
    VerificationChallengePurposeMismatchError,
)


@dataclass(frozen=True)
class ConfirmPasswordResetUseCase:
    uow: IUnitOfWork
    password_generator: IPasswordGenerator
    password_hasher: IPasswordHasher
    token_hasher: ITokenHasher
    clock: IClock

    async def execute(self, cmd: ConfirmPasswordResetCommand) -> ConfirmPasswordResetResult:
        if (
            not isinstance(cmd.token, str)
            or not cmd.token
            or len(cmd.token) > 512
            or any(char.isspace() for char in cmd.token)
        ):
            raise InvalidPasswordResetTokenError()

        token_hash = self.token_hasher.hash(cmd.token)
        async with self.uow:
            candidate = await self.uow.verification_challenges.get_by_token_hash(token_hash)
            if candidate is None or candidate.purpose != VerificationPurpose.PASSWORD_RESET:
                raise InvalidPasswordResetTokenError()

            # All reset operations for a user serialize here before locking challenges.
            user = await self.uow.users.get_by_id_for_update(candidate.user_id)
            if user is None or not user.is_active() or user.password_hash is None:
                raise InvalidPasswordResetTokenError()

            challenge = await self.uow.verification_challenges.get_by_token_hash_for_update(token_hash)
            if (
                challenge is None
                or challenge.id != candidate.id
                or challenge.user_id != user.id
                or challenge.token_hash != token_hash
            ):
                raise InvalidPasswordResetTokenError()
            now = self.clock.now()
            try:
                challenge.use(purpose=VerificationPurpose.PASSWORD_RESET, now=now)
            except (
                VerificationChallengeAlreadyUsedError,
                VerificationChallengeExpiredError,
                VerificationChallengePurposeMismatchError,
            ):
                raise InvalidPasswordResetTokenError() from None

            password = self.password_generator.generate()
            user.change_password(self.password_hasher.hash(password))
            await self.uow.users.save(user)
            await self.uow.verification_challenges.save(challenge)
            await self.uow.sessions.revoke_all_by_user_id(user.id, now=now)
            await self.uow.verification_challenges.invalidate_unused_by_user_id(
                user.id, purpose=VerificationPurpose.PASSWORD_RESET, now=now,
            )
            await self.uow.outbox.add(SendPasswordChangedNotification(
                user_id=user.id, email=user.email, changed_at=now,
            ))
            await self.uow.commit()

        return ConfirmPasswordResetResult(password=password.value)
