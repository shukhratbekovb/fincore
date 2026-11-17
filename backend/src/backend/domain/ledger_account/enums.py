from enum import Enum


class AccountType(str, Enum):
    ASSET = "asset"
    LIABILITY = "liability"


class AccountStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"
