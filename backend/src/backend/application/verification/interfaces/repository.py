from datetime import datetime
from typing import Protocol
from uuid import UUID

from backend.domain.verification.entities import VerificationChallenge
from backend.domain.verification.enums import VerificationPurpose


class IVerificationChallengeRepository(Protocol):
    async def add(self, challenge: VerificationChallenge) -> None: ...

    async def get_by_token_hash(self, token_hash: str) -> VerificationChallenge | None:
        """Read identity without locking; user_id, purpose and token_hash are immutable.

        Reset re-reads with a lock after locking the user. This initial read alone
        never authorizes a password change.
        """
        ...

    async def get_by_token_hash_for_update(
        self, token_hash: str,
    ) -> VerificationChallenge | None:
        """Load and lock the challenge until the current transaction ends."""
        ...

    async def save(self, challenge: VerificationChallenge) -> None: ...

    async def invalidate_unused_by_user_id(
            self, user_id: UUID, *, purpose: VerificationPurpose, now: datetime,
    ) -> None:
        """Set used_at=now on unused challenges for this user and purpose.

        Caller holds the user lock. Include all matching rows, not just unexpired
        ones, and preserve existing used_at. Use the same UoW transaction.
        """
        ...
