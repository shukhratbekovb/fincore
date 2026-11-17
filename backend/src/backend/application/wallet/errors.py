from backend.application.share.errors import ApplicationError


class WalletNumberAlreadyExistsError(ApplicationError):
    pass


class WalletNotFoundError(ApplicationError):
    pass


class WalletBalanceNotZeroError(ApplicationError):
    pass


class WalletAccountingStateError(ApplicationError):
    """The wallet's balance or liability account is missing or inconsistent."""
