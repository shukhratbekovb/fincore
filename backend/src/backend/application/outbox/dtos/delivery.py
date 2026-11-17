from dataclasses import dataclass, field
from uuid import UUID

from backend.application.share.messages import OutboxMessage


@dataclass(frozen=True)
class OutboxDelivery:
    id: UUID
    lock_token: UUID
    attempts: int
    message: OutboxMessage = field(repr=False)
