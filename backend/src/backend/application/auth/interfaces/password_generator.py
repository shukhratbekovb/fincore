from typing import Protocol

from backend.domain.user.value_objects import RawPassword


class IPasswordGenerator(Protocol):
    def generate(self) -> RawPassword: ...
