from backend.domain.share.errors import DomainError


class InvalidSandboxTopUpAmountError(DomainError):
    pass


class InvalidSandboxTopUpStateError(DomainError):
    pass


class SandboxTopUpNotPendingError(DomainError):
    pass
