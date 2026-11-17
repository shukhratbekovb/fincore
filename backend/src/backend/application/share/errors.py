class ApplicationError(Exception):
    pass


class EntityNotFoundError(ApplicationError):
    pass


class UnsupportedOutboxMessageError(ApplicationError):
    pass


class InvalidCursorError(ApplicationError):
    pass


class InvalidPaginationError(ApplicationError):
    pass


class RateLimiterUnavailableError(ApplicationError):
    pass
