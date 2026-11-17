from dataclasses import dataclass, field
from enum import Enum

from backend.domain.share.enums import CurrencyEnum
from backend.domain.wallet.enums import WalletStatusEnum


class WalletSortEnum(str, Enum):
    name_asc = "name:asc"
    name_desc = "name:desc"
    currency_asc = "currency:asc"
    currency_desc = "currency:desc"
    balance_asc = "balance:asc"
    balance_desc = "balance:desc"
    created_at_asc = "created_at:asc"
    created_at_desc = "created_at:desc"
    status_asc = "status:asc"
    status_desc = "status:desc"


@dataclass
class WalletFilter:
    currency: CurrencyEnum | None = field(default=None)
    status: WalletStatusEnum | None = field(default=None)
    sort_by: WalletSortEnum = field(default=WalletSortEnum.created_at_asc)
