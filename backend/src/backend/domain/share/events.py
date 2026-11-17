from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass(kw_only=True, frozen=True)
class Event:
    id: UUID = field(default_factory=uuid4)
