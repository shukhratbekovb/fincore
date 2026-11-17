from enum import Enum


class VerificationPurpose(str, Enum):
    REGISTRATION = "registration"
    PASSWORD_RESET = "password_reset"
