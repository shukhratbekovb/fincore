from datetime import datetime
from typing import Protocol
from uuid import UUID

from backend.domain.session.entities import Session, RefreshToken


class ISessionRepository(Protocol):
    async def add(self, session: Session) -> None: ...

    async def get_by_id(self, session_id: UUID) -> Session | None:
        """Read session identity; user_id must be immutable."""
        ...

    async def revoke_all_by_user_id(self, user_id: UUID, *, now: datetime) -> None:
        """Revoke all unrevoked sessions in this transaction, preserving prior revocations.

        Caller holds the user lock; update revoked_at and updated_at atomically.
        """
        ...

    async def get_by_id_for_update(self, session_id: UUID) -> Session | None:
        """Lock until transaction ends; return latest committed state."""
        ...

    async def get_active_by_user_id(self, user_id: UUID, *, now: datetime) -> list[Session]: ...

    async def save(self, session: Session) -> None: ...


class IRefreshTokenRepository(Protocol):
    """Token hashes are unique; session_id and token_hash are immutable.

    Retain consumed tokens until their session expires to detect reuse.
    """

    async def add(self, token: RefreshToken) -> None: ...

    async def get_by_token_hash(self, token_hash: str) -> RefreshToken | None: ...

    async def get_by_id_for_update(self, token_id: UUID) -> RefreshToken | None:
        """Lock and read latest state, after locking the owning session."""
        ...

    async def save(self, token: RefreshToken) -> None: ...
