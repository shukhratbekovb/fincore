import secrets

from backend.domain.wallet.value_objects import WALLET_NUMBER_LENGTH, WalletNumber


class RandomWalletNumberGenerator:
    def generate(self) -> WalletNumber:
        number = secrets.randbelow(10 ** WALLET_NUMBER_LENGTH)
        return WalletNumber(str(number).zfill(WALLET_NUMBER_LENGTH))
