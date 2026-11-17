from dataclasses import dataclass
from datetime import timedelta

from backend.application.auth.dtos.refresh import RefreshSessionCommand
from backend.application.auth.dtos.token import TokenResult
from backend.application.auth.errors import UserInactiveError
from backend.domain.session.errors import InvalidRefreshTokenError, RefreshTokenReuseError
from backend.application.auth.interfaces.token_issuer import ITokenIssuer
from backend.application.share.interfaces.clock import IClock
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.verification.interfaces.token_generator import ITokenGenerator
from backend.application.verification.interfaces.token_hasher import ITokenHasher
from backend.domain.session.entities import RefreshToken


@dataclass(frozen=True)
class RefreshSessionUseCase:
    uow: IUnitOfWork
    token_issuer: ITokenIssuer
    token_generator: ITokenGenerator
    token_hasher: ITokenHasher
    clock: IClock
    session_ttl: timedelta

    def __post_init__(self) -> None:
        if self.session_ttl <= timedelta(0):
            raise ValueError("Session TTL must be positive")

    async def execute(self, cmd: RefreshSessionCommand) -> TokenResult:
        reuse_detected = False
        async with self.uow:
            token_hash = self.token_hasher.hash(cmd.refresh_token)
            candidate = await self.uow.refresh_tokens.get_by_token_hash(token_hash)
            if candidate is None:
                raise InvalidRefreshTokenError()

            identity = await self.uow.sessions.get_by_id(candidate.session_id)
            if identity is None:
                raise InvalidRefreshTokenError()
            # Shared order with password change/login: user, session, then token.
            user = await self.uow.users.get_by_id_for_update(identity.user_id)
            if user is None:
                raise InvalidRefreshTokenError()
            session = await self.uow.sessions.get_by_id_for_update(candidate.session_id)
            if session is None or session.user_id != user.id:
                raise InvalidRefreshTokenError()
            current = await self.uow.refresh_tokens.get_by_id_for_update(candidate.id)
            now = self.clock.now()
            if current is None or current.session_id != session.id or current.token_hash != token_hash:
                raise InvalidRefreshTokenError()
            if session.revoked_at is not None or session.is_expired(now=now):
                raise InvalidRefreshTokenError()

            if current.used_at is not None:
                session.revoke(now=now)
                await self.uow.sessions.save(session)
                # Commit revocation before raising; otherwise UoW would roll it back.
                await self.uow.commit()
                reuse_detected = True
            else:
                if now >= current.expires_at:
                    raise InvalidRefreshTokenError()
                if not user.is_active():
                    raise UserInactiveError()

                new_token = self.token_generator.generate()
                replacement = RefreshToken(
                    session_id=session.id,
                    token_hash=self.token_hasher.hash(new_token),
                    expires_at=min(session.expires_at, now + self.session_ttl),
                )
                current.rotate(replacement_id=replacement.id, now=now)
                session.record_activity(
                    now=now, ip_address=cmd.ip_address, user_agent=cmd.user_agent,
                )
                access_token = self.token_issuer.encode(user.id)
                await self.uow.refresh_tokens.add(replacement)
                await self.uow.refresh_tokens.save(current)
                await self.uow.sessions.save(session)
                await self.uow.commit()

        if reuse_detected:
            raise RefreshTokenReuseError()
        return TokenResult(access_token=access_token, refresh_token=new_token)
