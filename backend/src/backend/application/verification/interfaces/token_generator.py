from typing import Protocol


class ITokenGenerator(Protocol):
    def generate(self) -> str:
        """Return a cryptographically secure, unpredictable token."""
        ...
