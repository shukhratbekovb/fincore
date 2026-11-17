from dataclasses import dataclass, field


@dataclass(frozen=True)
class LogoutUserCommand:
    refresh_token: str = field(repr=False)
