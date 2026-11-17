from backend.domain.share.errors import DomainError


class VerificationChallengeExpiredError(DomainError):
    pass


class VerificationChallengeAlreadyUsedError(DomainError):
    pass


class VerificationChallengePurposeMismatchError(DomainError):
    pass
