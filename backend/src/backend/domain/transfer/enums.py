from enum import Enum


class TransferStatusEnum(str, Enum):
    COMPLETED = "completed"
    PENDING = "pending"
    REJECTED = "rejected"


class TransferRejectionCodeEnum(str, Enum):
    INSUFFICIENT_FUNDS = "insufficient_funds"
    WALLET_NOT_ACTIVE = "wallet_not_active"
    CURRENCY_MISMATCH = "currency_mismatch"
    BALANCE_OVERFLOW = "balance_overflow"
