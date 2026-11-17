from dataclasses import dataclass
from datetime import timedelta

from backend.application.auth.dtos.login import LoginUserCommand
from backend.application.auth.dtos.token import TokenResult
from backend.application.auth.errors import InvalidCredentialsError, UserInactiveError
from backend.application.auth.interfaces.password_hasher import IPasswordHasher
from backend.application.auth.interfaces.token_issuer import ITokenIssuer
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.share.interfaces.clock import IClock
from backend.application.verification.interfaces.token_generator import ITokenGenerator
from backend.application.verification.interfaces.token_hasher import ITokenHasher
from backend.domain.session.entities import Session, RefreshToken


@dataclass(frozen=True)
class LoginUserUseCase:
    uow: IUnitOfWork
    password_hasher: IPasswordHasher
    token_issuer: ITokenIssuer
    token_generator: ITokenGenerator
    token_hasher: ITokenHasher
    clock: IClock
    session_ttl: timedelta

    def __post_init__(self) -> None:
        if self.session_ttl <= timedelta(0):
            raise ValueError("Session TTL must be positive")

    async def execute(
            self,
            cmd: LoginUserCommand
    ) -> TokenResult:
        async with self.uow:
            user = await self.uow.users.get_by_username(cmd.username)

            if user is None:
                raise InvalidCredentialsError()
            # Serialize with password changes before verifying the password.
            user = await self.uow.users.get_by_id_for_update(user.id)
            if user is None or user.password_hash is None:
                raise InvalidCredentialsError()

            if not self.password_hasher.verify(cmd.password, user.password_hash):
                raise InvalidCredentialsError()

            if not user.is_active():
                raise UserInactiveError()

            access_token = self.token_issuer.encode(user.id)
            token = self.token_generator.generate()
            token_hash = self.token_hasher.hash(token)

            session = Session.create(
                user_id=user.id,
                user_agent=cmd.user_agent,
                ip_address=cmd.ip_address,
                now=self.clock.now(),
                ttl=self.session_ttl,
            )
            user.login()
            await self.uow.sessions.add(session)
            await self.uow.refresh_tokens.add(RefreshToken(
                session_id=session.id,
                token_hash=token_hash,
                expires_at=session.expires_at,
            ))
            await self.uow.users.save(user)
            await self.uow.commit()

        return TokenResult(
            access_token=access_token,
            refresh_token=token
        )
