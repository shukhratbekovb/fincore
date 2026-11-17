from dataclasses import dataclass, field

from backend.domain.user.value_objects import Email


@dataclass(frozen=True)
class RequestPasswordResetCommand:
    email: Email


@dataclass(frozen=True)
class ConfirmPasswordResetCommand:
    token: str = field(repr=False)


@dataclass(frozen=True)
class ConfirmPasswordResetResult:
    # Returned once after commit. Never persist, log or put this value in outbox.
    password: str = field(repr=False)
