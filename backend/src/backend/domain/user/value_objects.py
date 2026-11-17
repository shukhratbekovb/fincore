import re
import string
from dataclasses import dataclass, field

from backend.domain.user.errors import InvalidPasswordError, InvalidEmailError, InvalidUsernameError

SPECIAL_CHARACTERS = string.punctuation


@dataclass(frozen=True)
class Username:
    value: str

    def __post_init__(self):
        if not isinstance(self.value, str):
            raise TypeError("Username should be a string")
        errors: list[str] = []

        if not 5 <= len(self.value) <= 256:
            errors.append(
                "Username must be between 5 and 256 characters"
            )

        if self.value:
            if not re.fullmatch(r"[a-zA-Z]", self.value[0]):
                errors.append(
                    "Username must start with a Latin letter"
                )

            if not re.fullmatch(r"[a-zA-Z0-9]", self.value[-1]):
                errors.append(
                    "Username must end with a Latin letter or digit"
                )

            if not re.fullmatch(r"[a-zA-Z0-9_]+", self.value):
                errors.append(
                    "Username must contain only Latin letters, "
                    "digits, and underscores"
                )

        if errors:
            raise InvalidUsernameError(errors)

        object.__setattr__(self, "value", self.value.lower())


@dataclass(frozen=True)
class Email:
    value: str

    def __post_init__(self):
        if not isinstance(self.value, str):
            raise TypeError("Email should be a string")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", self.value):
            raise InvalidEmailError("Incorrect email format")

        object.__setattr__(self, "value", self.value.lower())


@dataclass(frozen=True)
class PasswordCandidate:
    value: str = field(repr=False)

    def __post_init__(self):
        if not isinstance(self.value, str):
            raise TypeError("Password should be a string")
        if not 1 <= len(self.value) <= 256:
            raise InvalidPasswordError(["Password must be between 1 and 256 characters"])


@dataclass(frozen=True)
class RawPassword(PasswordCandidate):

    def __post_init__(self):
        if not isinstance(self.value, str):
            raise TypeError("Password should be a string")
        errors: list[str] = []

        if not (8 <= len(self.value) <= 256):
            errors.append("Password must be between 8 and 256 characters")
        if not any(char.isdigit() for char in self.value):
            errors.append("Password must contain digit")
        if not any(char.islower() for char in self.value):
            errors.append("Password must contain lowercase letter")
        if not any(char.isupper() for char in self.value):
            errors.append("Password must contain uppercase letter")
        if not any(char in SPECIAL_CHARACTERS for char in self.value):
            errors.append("Password must contain special characters")

        if errors:
            raise InvalidPasswordError(errors)


@dataclass(frozen=True)
class HashedPassword:
    value: str
