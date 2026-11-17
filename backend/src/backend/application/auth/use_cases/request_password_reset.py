from dataclasses import dataclass
from datetime import timedelta

from backend.application.auth.dtos.password_reset import RequestPasswordResetCommand
from backend.application.share.interfaces.clock import IClock
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.verification.interfaces.token_generator import ITokenGenerator
from backend.application.verification.interfaces.token_hasher import ITokenHasher
from backend.application.verification.messages import SendPasswordResetConfirmation
from backend.domain.verification.entities import VerificationChallenge
from backend.domain.verification.enums import VerificationPurpose


@dataclass(frozen=True)
class RequestPasswordResetUseCase:
    uow: IUnitOfWork
    token_generator: ITokenGenerator
    token_hasher: ITokenHasher
    clock: IClock
    reset_ttl: timedelta

    def __post_init__(self) -> None:
        if self.reset_ttl <= timedelta(0):
            raise ValueError("Password reset TTL must be positive")

    async def execute(self, cmd: RequestPasswordResetCommand) -> None:
        async with self.uow:
            # Do the same cryptographic work for unknown and known emails.
            # HTTP rate limits/timing protections are still required at integration.
            token = self.token_generator.generate()
            token_hash = self.token_hasher.hash(token)
            candidate = await self.uow.users.get_by_email(cmd.email)
            if candidate is None:
                return

            # Serialize creation with a reset; don't invalidate links on a public request.
            user = await self.uow.users.get_by_id_for_update(candidate.id)
            if user is None or user.email != cmd.email or not user.is_active() or user.password_hash is None:
                return

            challenge = VerificationChallenge(
                user_id=user.id,
                purpose=VerificationPurpose.PASSWORD_RESET,
                token_hash=token_hash,
                expires_at=self.clock.now() + self.reset_ttl,
            )
            await self.uow.verification_challenges.add(challenge)
            await self.uow.outbox.add(SendPasswordResetConfirmation(
                user_id=user.id, email=user.email, token=token, expires_at=challenge.expires_at,
            ))
            await self.uow.commit()
