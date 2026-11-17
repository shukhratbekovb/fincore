from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from backend.application.transfer.errors import InvalidTransferFilterError
from backend.domain.share.enums import CurrencyEnum
from backend.domain.transfer.enums import TransferStatusEnum


class TransferDirectionEnum(str, Enum):
    INCOMING = "incoming"
    OUTGOING = "outgoing"
    INTERNAL = "internal"


@dataclass(frozen=True, kw_only=True)
class TransferFilter:
    wallet_id: UUID | None = None
    currency: CurrencyEnum | None = None
    status: TransferStatusEnum | None = None
    direction: TransferDirectionEnum | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None

    def __post_init__(self) -> None:
        for value, expected_type in (
            (self.wallet_id, UUID),
            (self.currency, CurrencyEnum),
            (self.status, TransferStatusEnum),
            (self.direction, TransferDirectionEnum),
        ):
            if value is not None and not isinstance(value, expected_type):
                raise InvalidTransferFilterError()
        for value in (self.created_from, self.created_to):
            if value is not None and (
                not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None
            ):
                raise InvalidTransferFilterError()
        if self.created_from is not None and self.created_to is not None and self.created_from >= self.created_to:
            raise InvalidTransferFilterError("Creation range must have start before end")
