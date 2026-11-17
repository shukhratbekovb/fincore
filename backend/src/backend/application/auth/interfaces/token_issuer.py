from typing import Protocol
from uuid import UUID


class ITokenIssuer(Protocol):
    def encode(self, user_id: UUID) -> str: ...

    def decode(self, token: str) -> UUID: ...
