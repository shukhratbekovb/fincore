from enum import Enum


class SandboxTopUpStatusEnum(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    REJECTED = "rejected"


class SandboxTopUpRejectionCodeEnum(str, Enum):
    WALLET_NOT_ACTIVE = "wallet_not_active"
    BALANCE_OVERFLOW = "balance_overflow"
    LIMIT_EXCEEDED = "limit_exceeded"
