from dataclasses import dataclass

from backend.domain.user.value_objects import Email


@dataclass(frozen=True)
class ResendRegistrationConfirmationCommand:
    email: Email
