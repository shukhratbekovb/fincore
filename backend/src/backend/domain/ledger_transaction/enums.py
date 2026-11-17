from enum import Enum


class LedgerTransactionKindEnum(str, Enum):
    P2P_TRANSFER = "p2p_transfer"
    SANDBOX_TOPUP = "sandbox_topup"
