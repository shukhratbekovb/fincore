from backend.application.share.errors import ApplicationError


class InvalidIdempotencyKeyError(ApplicationError):
    pass


class IdempotencyConflictError(ApplicationError):
    pass


class IdempotencyInProgressError(ApplicationError):
    pass
