from backend.domain.share.errors import DomainError


class InvalidUsernameError(DomainError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("; ".join(self.errors))


class InvalidPasswordError(DomainError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("; ".join(self.errors))


class InvalidEmailError(DomainError):
    pass


class UserNotPendingConfirmationError(DomainError):
    pass
