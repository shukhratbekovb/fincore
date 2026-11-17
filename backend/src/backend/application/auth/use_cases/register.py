from dataclasses import dataclass
from datetime import timedelta

from backend.application.auth.dtos.register import RegisterUserCommand, RegisterUserResult
from backend.application.auth.errors import EmailAlreadyExistError, UsernameAlreadyExistError
from backend.application.share.interfaces.clock import IClock
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.verification.interfaces.token_generator import ITokenGenerator
from backend.application.verification.interfaces.token_hasher import ITokenHasher
from backend.application.verification.messages import SendRegistrationConfirmation
from backend.domain.user.entities import User
from backend.domain.verification.entities import VerificationChallenge
from backend.domain.verification.enums import VerificationPurpose


@dataclass(frozen=True)
class RegisterUserUseCase:
    uow: IUnitOfWork
    token_generator: ITokenGenerator
    token_hasher: ITokenHasher
    clock: IClock
    confirmation_ttl: timedelta

    def __post_init__(self) -> None:
        if self.confirmation_ttl <= timedelta(0):
            raise ValueError("Confirmation TTL must be positive")

    async def execute(self, cmd: RegisterUserCommand) -> RegisterUserResult:
        async with self.uow:
            if await self.uow.users.get_by_email(cmd.email):
                raise EmailAlreadyExistError()
            if await self.uow.users.get_by_username(cmd.username):
                raise UsernameAlreadyExistError()

            user = User.register(username=cmd.username, email=cmd.email)
            token = self.token_generator.generate()
            challenge = VerificationChallenge(
                user_id=user.id,
                purpose=VerificationPurpose.REGISTRATION,
                token_hash=self.token_hasher.hash(token),
                expires_at=self.clock.now() + self.confirmation_ttl,
            )

            await self.uow.users.add(user)
            await self.uow.verification_challenges.add(challenge)
            await self.uow.outbox.add(SendRegistrationConfirmation(
                user_id=user.id,
                email=user.email,
                token=token,
                expires_at=challenge.expires_at,
            ))
            await self.uow.commit()

        return RegisterUserResult(user_id=user.id)
