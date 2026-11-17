from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class GetTransferCommand:
    user_id: UUID
    transfer_id: UUID
