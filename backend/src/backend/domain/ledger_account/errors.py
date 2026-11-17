from backend.domain.share.errors import DomainError


class InvalidLedgerAccountCodeError(DomainError):
    pass


class InvalidLedgerAccountError(DomainError):
    pass


class LedgerAccountClosedError(DomainError):
    pass
