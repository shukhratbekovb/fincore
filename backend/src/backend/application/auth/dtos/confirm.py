from dataclasses import dataclass

from backend.domain.user.value_objects import RawPassword


@dataclass(frozen=True)
class ConfirmUserCommand:
    token: str
    password: RawPassword
