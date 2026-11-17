from typing import Protocol
from uuid import UUID

from backend.domain.user.entities import User
from backend.domain.user.value_objects import Email, Username


class IUserRepository(Protocol):
    async def add(self, user: User) -> None: ...

    async def get_by_id(self, user_id: UUID) -> User | None: ...

    async def get_by_id_for_update(self, user_id: UUID) -> User | None:
        """Load current user state and lock its row until the transaction ends.

        Concurrent updates must wait and then read the latest committed state.
        """
        ...

    async def get_by_email(self, email: Email) -> User | None: ...

    async def get_by_username(self, username: Username) -> User | None: ...

    async def save(self, user: User) -> None: ...
