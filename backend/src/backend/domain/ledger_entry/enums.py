from enum import Enum


class LedgerEntrySideEnum(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"
