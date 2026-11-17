from backend.application.share.errors import ApplicationError


class TransferCurrencyMismatchError(ApplicationError):
    pass


class TransferLimitExceededError(ApplicationError):
    pass


class TransferNotFoundError(ApplicationError):
    pass


class InvalidTransferFilterError(ApplicationError):
    pass
