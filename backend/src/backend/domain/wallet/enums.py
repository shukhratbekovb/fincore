from enum import Enum


class WalletStatusEnum(str, Enum):
    ACTIVE = 'active'
    CLOSED = 'closed'
    FROZEN = 'frozen'
