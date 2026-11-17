from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from backend.application.auth.interfaces.password_hasher import IPasswordHasher
from backend.domain.user.value_objects import RawPassword, PasswordCandidate, HashedPassword

ph = PasswordHasher()


class Argon2PasswordHasher(IPasswordHasher):
    def hash(self, raw_password: RawPassword) -> HashedPassword:
        return HashedPassword(ph.hash(raw_password.value))

    def verify(self, plain_password: PasswordCandidate, hashed_password: HashedPassword) -> bool:
        try:
            return ph.verify(
                hashed_password.value,
                plain_password.value
            )
        except VerifyMismatchError:
            return False
