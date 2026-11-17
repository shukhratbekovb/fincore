from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4


@dataclass(kw_only=True)
class IdentityMixin:
    id: UUID = field(default_factory=uuid4)


@dataclass(kw_only=True)
class TimeActionMixin:
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def _touch(self):
        self.updated_at = datetime.now(tz=timezone.utc)
