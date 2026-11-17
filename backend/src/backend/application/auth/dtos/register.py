from dataclasses import dataclass
from uuid import UUID

from backend.domain.user.value_objects import Email, Username


@dataclass(frozen=True)
class RegisterUserCommand:
    username: Username
    email: Email


@dataclass(frozen=True)
class RegisterUserResult:
    user_id: UUID
