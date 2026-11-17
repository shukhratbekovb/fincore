from dataclasses import dataclass, field


@dataclass(frozen=True)
class RefreshSessionCommand:
    refresh_token: str
    ip_address: str
    user_agent: str | None = field(default=None)
