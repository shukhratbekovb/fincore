from typing import Protocol

from backend.domain.user.value_objects import RawPassword, PasswordCandidate, HashedPassword


class IPasswordHasher(Protocol):
    def hash(self, raw_password: RawPassword) -> HashedPassword: ...

    def verify(self, plain_password: PasswordCandidate, hashed_password: HashedPassword) -> bool: ...
