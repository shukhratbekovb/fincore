from backend.domain.share.errors import DomainError


class InvalidWalletBalanceError(DomainError):
    pass


class InvalidBalanceAmountError(DomainError):
    pass


class InsufficientFundsError(DomainError):
    pass


class WalletBalanceOverflowError(DomainError):
    pass
