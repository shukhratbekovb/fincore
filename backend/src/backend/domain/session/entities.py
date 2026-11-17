from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from backend.domain.share.entities import BaseEntity
from backend.domain.share.mixins import IdentityMixin, TimeActionMixin

@dataclass(kw_only=True)
class Session(
    IdentityMixin,
    TimeActionMixin,
    BaseEntity
):
    user_id: UUID
    expires_at: datetime
    ip_address: str
    last_used_at: datetime | None = None
    last_ip_address: str | None = None
    last_user_agent: str | None = None
    revoked_at: datetime | None = field(default=None)
    user_agent: str | None = field(default=None)

    def __post_init__(self) -> None:
        for value in (self.created_at, self.updated_at, self.expires_at, self.revoked_at, self.last_used_at):
            if value is not None:
                self._require_aware_datetime(value)

    def revoke(self, *, now: datetime) -> None:
        self._require_aware_datetime(now)
        if self.revoked_at is None:
            self.revoked_at = now
            self.updated_at = now

    def record_activity(self, *, now: datetime, ip_address: str, user_agent: str | None) -> None:
        self._require_aware_datetime(now)
        self.last_used_at = now
        self.last_ip_address = ip_address
        self.last_user_agent = user_agent
        self.updated_at = now

    def is_expired(self, *, now: datetime) -> bool:
        self._require_aware_datetime(now)
        return self.expires_at <= now

    @classmethod
    def create(
            cls,
            user_id: UUID,
            ip_address: str,
            *,
            now: datetime,
            ttl: timedelta,
            user_agent: str | None = None
    ) -> "Session":
        cls._require_aware_datetime(now)
        if ttl <= timedelta(0):
            raise ValueError("Session TTL must be positive")

        return cls(
            user_id=user_id,
            ip_address=ip_address,
            created_at=now,
            updated_at=now,
            expires_at=now + ttl,
            user_agent=user_agent
        )

    @staticmethod
    def _require_aware_datetime(value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Session timestamps must be timezone-aware")


@dataclass(kw_only=True)
class RefreshToken(IdentityMixin, BaseEntity):
    session_id: UUID
    token_hash: str = field(repr=False)
    expires_at: datetime
    used_at: datetime | None = None
    replaced_by_id: UUID | None = None

    def __post_init__(self) -> None:
        Session._require_aware_datetime(self.expires_at)
        if self.used_at is not None:
            Session._require_aware_datetime(self.used_at)

    def rotate(self, *, replacement_id: UUID, now: datetime) -> None:
        from backend.domain.session.errors import InvalidRefreshTokenError

        Session._require_aware_datetime(now)
        if self.used_at is not None or now >= self.expires_at:
            raise InvalidRefreshTokenError()
        self.used_at = now
        self.replaced_by_id = replacement_id
