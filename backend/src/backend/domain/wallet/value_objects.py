from dataclasses import dataclass

from backend.domain.wallet.errors import InvalidWalletNameError, InvalidWalletNumberError

WALLET_NAME_MAX_LENGTH = 64
WALLET_NUMBER_LENGTH = 20


@dataclass(frozen=True)
class WalletName:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("Wallet name must be a string")
        normalized = self.value.strip()
        if not 1 <= len(normalized) <= WALLET_NAME_MAX_LENGTH:
            raise InvalidWalletNameError(
                f"Wallet name must be between 1 and {WALLET_NAME_MAX_LENGTH} characters"
            )
        object.__setattr__(self, "value", normalized)


@dataclass(frozen=True)
class WalletNumber:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("Wallet number must be a string")
        if (
            len(self.value) != WALLET_NUMBER_LENGTH
            or not self.value.isascii()
            or not self.value.isdigit()
        ):
            raise InvalidWalletNumberError(
                f"Wallet number must contain exactly {WALLET_NUMBER_LENGTH} ASCII digits"
            )
