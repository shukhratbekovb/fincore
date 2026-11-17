from dataclasses import dataclass, field
from uuid import UUID

from backend.domain.share.entities import BaseEntity
from backend.domain.share.enums import CurrencyEnum
from backend.domain.share.mixins import IdentityMixin, TimeActionMixin
from backend.domain.wallet.enums import WalletStatusEnum
from backend.domain.wallet.errors import (
    WalletClosedError,
    WalletNotActiveError,
    WalletNotFrozenError,
)
from backend.domain.wallet.value_objects import WalletName, WalletNumber


@dataclass(kw_only=True)
class Wallet(
    IdentityMixin,
    TimeActionMixin,
    BaseEntity
):
    user_id: UUID
    name: WalletName
    number: WalletNumber
    currency: CurrencyEnum = field(default=CurrencyEnum.USD)
    status: WalletStatusEnum = field(default=WalletStatusEnum.ACTIVE)

    @classmethod
    def create(
            cls,
            user_id: UUID,
            name: WalletName,
            number: WalletNumber,
            currency: CurrencyEnum,
    ) -> "Wallet":
        return cls(
            user_id=user_id,
            name=name,
            number=number,
            currency=currency
        )

    def unfreeze(self) -> None:
        self._ensure_not_closed()
        if self.status != WalletStatusEnum.FROZEN:
            raise WalletNotFrozenError()
        self.status = WalletStatusEnum.ACTIVE
        self._touch()

    def close(self) -> None:
        if self.status == WalletStatusEnum.CLOSED:
            return
        self.status = WalletStatusEnum.CLOSED
        self._touch()

    def freeze(self) -> None:
        self._ensure_not_closed()
        if self.status != WalletStatusEnum.ACTIVE:
            raise WalletNotActiveError()
        self.status = WalletStatusEnum.FROZEN
        self._touch()

    def change_name(self, new_name: WalletName) -> None:
        self._ensure_not_closed()
        self.name = new_name
        self._touch()

    def _ensure_not_closed(self) -> None:
        if self.status == WalletStatusEnum.CLOSED:
            raise WalletClosedError()

    def is_active(self) -> bool:
        return self.status == WalletStatusEnum.ACTIVE
