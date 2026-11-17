from typing import Protocol
from uuid import UUID

from backend.application.idempotency.dtos import IdempotencyRecord


class IIdempotencyRepository(Protocol):
    """Reservations and results participate in the caller's UoW transaction.

    UNIQUE(user_id, scope, key) is mandatory. Retain completed results for at
    least 24 hours. Never commit independently or commit an unfinished claim.
    """

    async def claim(
            self,
            *,
            user_id: UUID,
            scope: str,
            key: str,
            payload_hash: str,
    ) -> IdempotencyRecord | None:
        """Atomically reserve a new key, returning None only to its owner.

        For an existing key return the stored hash/result. A concurrent caller
        must wait within a bounded timeout or raise IdempotencyInProgressError;
        it must never also become owner of the same reservation. Rollback
        releases a new reservation, allowing the entire command to be retried.
        """
        ...

    async def complete(
            self,
            *,
            user_id: UUID,
            scope: str,
            key: str,
            payload_hash: str,
            resource_id: UUID,
    ) -> None:
        """Complete the reservation owned by this transaction, checking hash.

        This stores the entire current result (resource ID). Commands returning
        richer results must extend replay storage to preserve their full result.
        """
        ...
