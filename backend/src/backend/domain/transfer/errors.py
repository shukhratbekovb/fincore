from backend.domain.share.errors import DomainError


class SameWalletTransferError(DomainError):
    pass


class InvalidTransferAmountError(DomainError):
    pass


class TransferNotPendingError(DomainError):
    pass


class InvalidTransferStateError(DomainError):
    pass
