from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class SessionDTO:
    id: UUID
    expires_at: datetime
    ip_address: str
    last_ip_address: str | None = None
    last_user_agent: str | None = None
    last_used_at: datetime | None = None
    created_at: datetime | None = None
    user_agent: str | None = field(default=None)
