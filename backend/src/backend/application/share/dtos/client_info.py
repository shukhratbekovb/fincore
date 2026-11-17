from dataclasses import dataclass


@dataclass(frozen=True)
class ClientInfo:
    ip_address: str
    user_agent: str | None = None
