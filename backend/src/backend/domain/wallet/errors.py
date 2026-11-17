from backend.domain.share.errors import DomainError


class InvalidWalletNameError(DomainError):
    pass


class InvalidWalletNumberError(DomainError):
    pass


class WalletClosedError(DomainError):
    pass


class WalletNotActiveError(DomainError):
    pass


class WalletNotFrozenError(DomainError):
    pass
