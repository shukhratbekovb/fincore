from typing import Protocol


class ITokenHasher(Protocol):
    def hash(self, token: str) -> str:
        """Return a deterministic digest suitable for token lookup."""
        ...
