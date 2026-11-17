from backend.domain.share.errors import DomainError


class InvalidRefreshTokenError(DomainError):
    pass


class RefreshTokenReuseError(InvalidRefreshTokenError):
    pass
