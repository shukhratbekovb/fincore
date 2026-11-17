import hmac
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Query
from pydantic import AwareDatetime

from backend.application.history.dtos.filters import MyTransactionsFilter, WalletTransactionFilter, TransactionDirectionEnum
from backend.application.history.queries.get_my_transactions import GetMyTransactionsQuery
from backend.application.sandbox_top_up.use_cases.create_top_up import CreateSandboxTopUpUseCase
from backend.application.transfer.dtos.filters import TransferFilter, TransferDirectionEnum
from backend.application.transfer.queries.get_transfer import GetTransferQuery
from backend.application.transfer.queries.get_my_transfers import GetMyTransfersQuery
from backend.application.transfer.use_cases.create_transfer import CreateTransferUseCase
from backend.application.wallet.queries.get_wallet_transactions import GetWalletTransactionsQuery
from backend.application.wallet.queries.get_wallet_balance import GetWalletBalanceQuery
from backend.application.wallet.queries.get_my_balance_summary import GetMyBalanceSummaryQuery
from backend.domain.ledger_transaction.enums import LedgerTransactionKindEnum
from backend.domain.share.enums import CurrencyEnum
from backend.domain.transfer.enums import TransferStatusEnum
from backend.infrastructure.pagination.cursor import HMACCursorCodec
from backend.presentation.api.v1.dependencies.core import UowDep, ClockDep, SettingsDep


def get_cursor_codec(settings: SettingsDep) -> HMACCursorCodec:
    if settings.pagination_secret_key is not None:
        key = settings.pagination_secret_key.get_secret_value().encode('utf-8')
    elif settings.jwt_secret_key is not None:
        key = hmac.digest(settings.jwt_secret_key.get_secret_value().encode('utf-8'), b'fincore-pagination-v1', 'sha256')
    else:
        raise RuntimeError("A server signing key must be configured")
    return HMACCursorCodec(key=key)


CursorCodecDep = Annotated[HMACCursorCodec, Depends(get_cursor_codec)]
IdempotencyKeyDep = Annotated[str, Header(alias='Idempotency-Key', min_length=1, max_length=255, pattern=r'^[!-~]+$')]
PageLimit = Annotated[int, Query(ge=1, le=100)]


def get_create_transfer_use_case(uow: UowDep, clock: ClockDep, settings: SettingsDep) -> CreateTransferUseCase:
    return CreateTransferUseCase(uow=uow, clock=clock, max_amount_minor=settings.transfer_max_amount_minor)


def get_create_sandbox_top_up_use_case(uow: UowDep, clock: ClockDep, settings: SettingsDep) -> CreateSandboxTopUpUseCase:
    return CreateSandboxTopUpUseCase(uow=uow, clock=clock, sandbox_enabled=settings.sandbox_enabled, max_amount_minor=settings.sandbox_max_amount_minor)


def get_transfer_query(uow: UowDep) -> GetTransferQuery:
    return GetTransferQuery(uow=uow)


def get_my_transfers_query(uow: UowDep, cursor_codec: CursorCodecDep) -> GetMyTransfersQuery:
    return GetMyTransfersQuery(uow=uow, cursor_codec=cursor_codec)


def get_my_transactions_query(uow: UowDep, cursor_codec: CursorCodecDep) -> GetMyTransactionsQuery:
    return GetMyTransactionsQuery(uow=uow, cursor_codec=cursor_codec)


def get_wallet_transactions_query(uow: UowDep, cursor_codec: CursorCodecDep) -> GetWalletTransactionsQuery:
    return GetWalletTransactionsQuery(uow=uow, cursor_codec=cursor_codec)


def get_wallet_balance_query(uow: UowDep) -> GetWalletBalanceQuery:
    return GetWalletBalanceQuery(uow=uow)


def get_my_balance_summary_query(uow: UowDep) -> GetMyBalanceSummaryQuery:
    return GetMyBalanceSummaryQuery(uow=uow)


def get_transfer_filters(
        wallet_id: UUID | None = None, currency: CurrencyEnum | None = None,
        status: TransferStatusEnum | None = None, direction: TransferDirectionEnum | None = None,
        created_from: AwareDatetime | None = None, created_to: AwareDatetime | None = None,
) -> TransferFilter:
    return TransferFilter(wallet_id=wallet_id, currency=currency, status=status, direction=direction, created_from=created_from, created_to=created_to)


def get_wallet_transaction_filters(
        kind: LedgerTransactionKindEnum | None = None, currency: CurrencyEnum | None = None,
        direction: TransactionDirectionEnum | None = None,
        posted_from: AwareDatetime | None = None, posted_to: AwareDatetime | None = None,
) -> WalletTransactionFilter:
    return WalletTransactionFilter(kind=kind, currency=currency, direction=direction, posted_from=posted_from, posted_to=posted_to)


def get_my_transaction_filters(
        wallet_id: UUID | None = None, kind: LedgerTransactionKindEnum | None = None,
        currency: CurrencyEnum | None = None, direction: TransactionDirectionEnum | None = None,
        posted_from: AwareDatetime | None = None, posted_to: AwareDatetime | None = None,
) -> MyTransactionsFilter:
    return MyTransactionsFilter(wallet_id=wallet_id, kind=kind, currency=currency, direction=direction, posted_from=posted_from, posted_to=posted_to)


CreateTransferDep = Annotated[CreateTransferUseCase, Depends(get_create_transfer_use_case)]
CreateSandboxTopUpDep = Annotated[CreateSandboxTopUpUseCase, Depends(get_create_sandbox_top_up_use_case)]
GetTransferQueryDep = Annotated[GetTransferQuery, Depends(get_transfer_query)]
GetMyTransfersQueryDep = Annotated[GetMyTransfersQuery, Depends(get_my_transfers_query)]
GetMyTransactionsQueryDep = Annotated[GetMyTransactionsQuery, Depends(get_my_transactions_query)]
GetWalletTransactionsQueryDep = Annotated[GetWalletTransactionsQuery, Depends(get_wallet_transactions_query)]
GetWalletBalanceQueryDep = Annotated[GetWalletBalanceQuery, Depends(get_wallet_balance_query)]
GetMyBalanceSummaryQueryDep = Annotated[GetMyBalanceSummaryQuery, Depends(get_my_balance_summary_query)]
TransferFilterDep = Annotated[TransferFilter, Depends(get_transfer_filters)]
WalletTransactionFilterDep = Annotated[WalletTransactionFilter, Depends(get_wallet_transaction_filters)]
MyTransactionsFilterDep = Annotated[MyTransactionsFilter, Depends(get_my_transaction_filters)]
