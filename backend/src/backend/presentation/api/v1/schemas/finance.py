from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, BeforeValidator, PlainSerializer

from backend.application.history.dtos.filters import TransactionDirectionEnum
from backend.application.transfer.dtos.filters import TransferDirectionEnum
from backend.domain.ledger_transaction.enums import LedgerTransactionKindEnum
from backend.domain.share.enums import CurrencyEnum
from backend.domain.transfer.enums import TransferStatusEnum, TransferRejectionCodeEnum


def _parse_minor(value):
    if type(value) is int:
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 19:
        return int(value)
    raise ValueError("Amount must be an integer or decimal integer string")


RequestAmount = Annotated[int, BeforeValidator(_parse_minor, json_schema_input_type=int | str), Field(gt=0, le=2 ** 63 - 1)]
MoneyAmount = Annotated[int, Field(ge=0), PlainSerializer(str, return_type=str, when_used='json')]


class CreateTransferSchema(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sender_wallet_id: UUID
    receiver_wallet_id: UUID
    amount_minor: RequestAmount
    currency: CurrencyEnum


class CreateSandboxTopUpSchema(BaseModel):
    model_config = ConfigDict(extra='forbid')
    wallet_id: UUID
    amount_minor: RequestAmount
    currency: CurrencyEnum


class CreateTransferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    transfer_id: UUID


class CreateSandboxTopUpResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    top_up_id: UUID


class TransferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sender_wallet_id: UUID
    receiver_wallet_id: UUID
    amount_minor: MoneyAmount
    currency: CurrencyEnum
    status: TransferStatusEnum
    direction: TransferDirectionEnum
    created_at: AwareDatetime
    completed_at: AwareDatetime | None
    rejection_code: TransferRejectionCodeEnum | None


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source_type: LedgerTransactionKindEnum
    source_id: UUID
    sender_wallet_id: UUID | None
    receiver_wallet_id: UUID
    amount_minor: MoneyAmount
    currency: CurrencyEnum
    direction: TransactionDirectionEnum
    posted_at: AwareDatetime


class WalletTransactionResponse(TransactionResponse):
    wallet_id: UUID
    counterparty_wallet_id: UUID | None


class PageResponse[T](BaseModel):
    model_config = ConfigDict(from_attributes=True)
    items: list[T]
    next_cursor: str | None


class CurrencyBalanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    currency: CurrencyEnum
    posted_minor: MoneyAmount
    available_minor: MoneyAmount
    spendable_minor: MoneyAmount


class WalletBalanceResponse(CurrencyBalanceResponse):
    wallet_id: UUID
    version: Annotated[int, PlainSerializer(str, return_type=str, when_used='json')]
    updated_at: AwareDatetime
    as_of: AwareDatetime


class BalanceSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    totals: list[CurrencyBalanceResponse]
    as_of: AwareDatetime
