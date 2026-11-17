from backend.domain.share.errors import DomainError


class InvalidLedgerTransactionError(DomainError):
    pass


class UnbalancedLedgerTransactionError(InvalidLedgerTransactionError):
    pass
