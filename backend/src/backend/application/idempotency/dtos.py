from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, kw_only=True)
class IdempotencyRecord:
    payload_hash: str
    resource_id: UUID | None
