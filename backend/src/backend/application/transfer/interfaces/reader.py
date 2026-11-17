from typing import Protocol
from uuid import UUID

from backend.application.share.dtos.pagination import CursorPosition
from backend.application.transfer.dtos.base import TransferDTO
from backend.application.transfer.dtos.filters import TransferFilter


class ITransferReader(Protocol):
    """Scoped read projections; no row locks, writes or independent commits.

    Apply participation in SQL: sender owner OR receiver owner = user_id.
    Direction is always relative to the user, including with a wallet filter:
    INTERNAL if both owners match, otherwise INCOMING or OUTGOING.
    Never return private user data or counterparty balances.
    """

    async def get_by_id_for_user(
            self,
            transfer_id: UUID,
            *,
            user_id: UUID,
    ) -> TransferDTO | None:
        """Return None for both missing and non-participant transfers."""
        ...

    async def list_by_user_id(
            self,
            user_id: UUID,
            filters: TransferFilter,
            *,
            limit: int,
            cursor: CursorPosition | None,
    ) -> list[TransferDTO]:
        """Return up to limit rows ordered by (created_at DESC, id DESC).

        Apply tuple < cursor when provided. The handler requests page size + 1
        (at most 101). Deduplicate internal transfers before LIMIT, not afterward.
        If wallet_id is set it must belong to user_id; a foreign or missing
        wallet produces an empty list, never matches via the other participant.
        Creation range is [created_from, created_to). Filters only narrow the
        mandatory user scope. Closed/frozen wallets remain readable.
        """
        ...
