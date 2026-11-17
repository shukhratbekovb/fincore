from dataclasses import dataclass
from uuid import UUID

from backend.domain.share.events import Event
from backend.domain.user.value_objects import Email


@dataclass(frozen=True, kw_only=True)
class UserRegistered(Event):
    user_id: UUID
    email: Email
