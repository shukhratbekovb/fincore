from dataclasses import dataclass

from backend.application.auth.dtos.confirm import ConfirmUserCommand
from backend.application.auth.interfaces.password_hasher import IPasswordHasher
from backend.application.share.interfaces.clock import IClock
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.verification.interfaces.token_hasher import ITokenHasher
from backend.application.user.errors import UserNotFoundError
from backend.application.verification.errors import VerificationChallengeNotFoundError
from backend.domain.verification.enums import VerificationPurpose
from backend.domain.verification.errors import VerificationChallengePurposeMismatchError


@dataclass(frozen=True)
class ConfirmUserUseCase:
    uow: IUnitOfWork
    password_hasher: IPasswordHasher
    token_hasher: ITokenHasher
    clock: IClock

    async def execute(
            self,
            cmd: ConfirmUserCommand
    ) -> None:
        async with self.uow:
            token_hash = self.token_hasher.hash(cmd.token)

            candidate = await self.uow.verification_challenges.get_by_token_hash(token_hash)
            if candidate is None:
                raise VerificationChallengeNotFoundError()

            if candidate.purpose != VerificationPurpose.REGISTRATION:
                raise VerificationChallengePurposeMismatchError()

            # Match resend/reset lock order. The initial read only identifies the
            # user; authorization uses the locked challenge re-read below.
            user = await self.uow.users.get_by_id_for_update(candidate.user_id)

            if user is None:
                raise UserNotFoundError()

            challenge = await self.uow.verification_challenges.get_by_token_hash_for_update(token_hash)
            if (
                challenge is None or challenge.id != candidate.id
                or challenge.user_id != user.id or challenge.token_hash != token_hash
            ):
                raise VerificationChallengeNotFoundError()

            challenge.use(
                purpose=VerificationPurpose.REGISTRATION,
                now=self.clock.now()
            )

            hashed_password = self.password_hasher.hash(cmd.password)

            user.confirm(
                hashed_password
            )

            await self.uow.users.save(user)
            await self.uow.verification_challenges.save(challenge)

            await self.uow.commit()
