from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from backend.domain.user.value_objects import Username, Email


@dataclass(frozen=True)
class UserDTO:
    id: UUID
    username: Username
    email: Email
    created_at: datetime
