from backend.application.share.errors import ApplicationError


class SandboxDisabledError(ApplicationError):
    pass


class SandboxOperatorRequiredError(ApplicationError):
    pass


class SandboxTopUpCurrencyMismatchError(ApplicationError):
    pass


class SandboxTopUpLimitExceededError(ApplicationError):
    pass


class SandboxFundingAccountError(ApplicationError):
    """The system funding account is missing or inconsistent."""
