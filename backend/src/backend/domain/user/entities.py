from dataclasses import dataclass, field
from datetime import datetime, timezone

from backend.domain.share.entities import BaseEntity
from backend.domain.share.mixins import IdentityMixin, TimeActionMixin
from backend.domain.user.enums import UserStatusEnum
from backend.domain.user.errors import UserNotPendingConfirmationError
from backend.domain.user.value_objects import Email, HashedPassword, Username


@dataclass(kw_only=True)
class User(
    IdentityMixin,
    TimeActionMixin,
    BaseEntity
):
    username: Username
    email: Email
    password_hash: HashedPassword | None = field(default=None)
    status: UserStatusEnum = field(default=UserStatusEnum.ACTIVE)
    last_login_at: datetime | None = field(default=None)

    @classmethod
    def register(
            cls,
            username: Username,
            email: Email
    ) -> "User":
        return cls(
            username=username,
            email=email,
            status=UserStatusEnum.PENDING_CONFIRMATION
        )

    @classmethod
    def created_by_admin(
            cls,
            username: Username,
            email: Email,
            password_hash: HashedPassword
    ) -> "User":
        return cls(
            username=username,
            email=email,
            password_hash=password_hash,
        )

    def change_password(
            self,
            new_password: HashedPassword
    ) -> None:
        self.password_hash = new_password
        self._touch()

    def login(self) -> None:
        self.last_login_at = datetime.now(tz=timezone.utc)

    def close(self) -> None:
        self.status = UserStatusEnum.CLOSED
        self._touch()

    def activate(self) -> None:
        self.status = UserStatusEnum.ACTIVE
        self._touch()

    def suspend(self) -> None:
        self.status = UserStatusEnum.SUSPENDED
        self._touch()

    def confirm(
            self,
            password_hash: HashedPassword
    ) -> None:
        if self.status != UserStatusEnum.PENDING_CONFIRMATION:
            raise UserNotPendingConfirmationError()

        self.password_hash = password_hash
        self.status = UserStatusEnum.ACTIVE
        self._touch()

    def is_active(self) -> bool:
        return self.status == UserStatusEnum.ACTIVE
