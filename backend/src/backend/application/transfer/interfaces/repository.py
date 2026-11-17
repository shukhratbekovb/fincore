from typing import Protocol

from backend.domain.transfer.entities import Transfer


class ITransferRepository(Protocol):
    """Persist in the caller's UoW; never commit a PENDING transfer.

    Successful transfers must be committed with exactly one balanced journal
    and both balance projections. Never commit independently.
    """

    async def add(self, transfer: Transfer) -> None: ...
