import re
from dataclasses import dataclass

from backend.domain.ledger_account.errors import InvalidLedgerAccountCodeError

ACCOUNT_CODE_MAX_LENGTH = 80


@dataclass(frozen=True)
class LedgerAccountCode:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("Ledger account code must be a string")
        if (
            not 1 <= len(self.value) <= ACCOUNT_CODE_MAX_LENGTH
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_-]*", self.value) is None
        ):
            raise InvalidLedgerAccountCodeError(
                "Ledger account code must contain 1–80 ASCII letters, digits, "
                "colons, underscores or hyphens, and start with a letter or digit"
            )
