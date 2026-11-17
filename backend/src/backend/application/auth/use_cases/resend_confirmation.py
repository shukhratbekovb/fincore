from dataclasses import dataclass
from datetime import timedelta

from backend.application.auth.dtos.resend_confirmation import ResendRegistrationConfirmationCommand
from backend.application.share.interfaces.clock import IClock
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.verification.interfaces.token_generator import ITokenGenerator
from backend.application.verification.interfaces.token_hasher import ITokenHasher
from backend.application.verification.messages import SendRegistrationConfirmation
from backend.domain.user.enums import UserStatusEnum
from backend.domain.verification.entities import VerificationChallenge
from backend.domain.verification.enums import VerificationPurpose


@dataclass(frozen=True)
class ResendRegistrationConfirmationUseCase:
    uow: IUnitOfWork
    token_generator: ITokenGenerator
    token_hasher: ITokenHasher
    clock: IClock
    confirmation_ttl: timedelta

    def __post_init__(self) -> None:
        if self.confirmation_ttl <= timedelta(0):
            raise ValueError("Confirmation TTL must be positive")

    async def execute(self, cmd: ResendRegistrationConfirmationCommand) -> None:
        async with self.uow:
            # Generate and hash for every valid email; the HTTP result is generic.
            token = self.token_generator.generate()
            token_hash = self.token_hasher.hash(token)
            candidate = await self.uow.users.get_by_email(cmd.email)
            if candidate is None:
                return

            # Confirm and resend both lock the user before locking challenges.
            user = await self.uow.users.get_by_id_for_update(candidate.id)
            if (
                user is None or user.email != cmd.email
                or user.status != UserStatusEnum.PENDING_CONFIRMATION
            ):
                return

            now = self.clock.now()
            await self.uow.verification_challenges.invalidate_unused_by_user_id(
                user.id, purpose=VerificationPurpose.REGISTRATION, now=now,
            )
            challenge = VerificationChallenge(
                user_id=user.id, purpose=VerificationPurpose.REGISTRATION,
                token_hash=token_hash, expires_at=now + self.confirmation_ttl,
            )
            await self.uow.verification_challenges.add(challenge)
            await self.uow.outbox.add(SendRegistrationConfirmation(
                user_id=user.id, email=user.email, token=token, expires_at=challenge.expires_at,
            ))
            await self.uow.commit()
