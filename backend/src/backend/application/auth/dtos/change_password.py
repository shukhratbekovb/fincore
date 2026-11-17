from dataclasses import dataclass, field
from uuid import UUID

from backend.domain.user.value_objects import RawPassword


@dataclass(frozen=True)
class ChangePasswordCommand:
    # Supplied by the authenticated server context, never from a request body.
    user_id: UUID
    current_password: RawPassword = field(repr=False)
    new_password: RawPassword = field(repr=False)
