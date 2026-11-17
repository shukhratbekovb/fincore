from backend.application.share.errors import ApplicationError


class EmailAlreadyExistError(ApplicationError):
    pass


class UsernameAlreadyExistError(ApplicationError):
    pass


class InvalidCredentialsError(ApplicationError):
    pass


class UserInactiveError(ApplicationError):
    pass


class InvalidAccessTokenError(ApplicationError):
    pass


class AccessTokenExpiredError(InvalidAccessTokenError):
    pass


class InvalidPasswordResetTokenError(ApplicationError):
    """Unknown, expired, consumed or otherwise ineligible password reset."""

    pass
