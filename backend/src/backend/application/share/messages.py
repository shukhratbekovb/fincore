from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass(frozen=True, kw_only=True)
class OutboxMessage:
    id: UUID = field(default_factory=uuid4)
