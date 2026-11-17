from dataclasses import dataclass, field

from backend.domain.user.value_objects import Username, PasswordCandidate


@dataclass(frozen=True)
class LoginUserCommand:
    username: Username
    password: PasswordCandidate
    ip_address: str
    user_agent: str | None = field(default=None)
