from typing import Protocol

from backend.domain.wallet.value_objects import WalletNumber


class WalletNumberGenerator(Protocol):
    def generate(self) -> WalletNumber:
        """Generate a candidate locally; database uniqueness is authoritative."""
        ...
