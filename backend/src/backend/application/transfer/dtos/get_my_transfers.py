from dataclasses import dataclass, field
from uuid import UUID

from backend.application.transfer.dtos.filters import TransferFilter


@dataclass(frozen=True)
class GetMyTransfersCommand:
    user_id: UUID
    filters: TransferFilter = field(default_factory=TransferFilter)
    limit: int = 20
    cursor: str | None = None
