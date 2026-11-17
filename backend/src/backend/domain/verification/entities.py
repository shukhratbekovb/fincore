from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from backend.domain.share.entities import BaseEntity
from backend.domain.share.mixins import IdentityMixin
from backend.domain.verification.enums import VerificationPurpose
from backend.domain.verification.errors import (
    VerificationChallengeAlreadyUsedError,
    VerificationChallengeExpiredError,
    VerificationChallengePurposeMismatchError,
)


@dataclass(kw_only=True)
class VerificationChallenge(IdentityMixin, BaseEntity):
    user_id: UUID
    purpose: VerificationPurpose
    token_hash: str = field(repr=False)
    expires_at: datetime
    used_at: datetime | None = None

    def __post_init__(self) -> None:
        self._require_aware_datetime(self.expires_at)
        if self.used_at is not None:
            self._require_aware_datetime(self.used_at)

    def use(self, *, purpose: VerificationPurpose, now: datetime) -> None:
        """Consume a challenge after the application has verified its token."""
        self._require_aware_datetime(now)

        if self.purpose != purpose:
            raise VerificationChallengePurposeMismatchError()
        if self.used_at is not None:
            raise VerificationChallengeAlreadyUsedError()
        if now >= self.expires_at:
            raise VerificationChallengeExpiredError()

        self.used_at = now

    @staticmethod
    def _require_aware_datetime(value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Verification timestamps must be timezone-aware")
