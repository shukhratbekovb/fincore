from typing import Annotated

from fastapi import Depends

from backend.application.wallet.use_cases.create_wallet import CreateWalletUseCase
from backend.application.wallet.use_cases.rename_wallet import RenameWalletUseCase
from backend.application.wallet.use_cases.close_wallet import CloseWalletUseCase
from backend.application.wallet.use_cases.freeze_wallet import FreezeWalletUseCase
from backend.application.wallet.use_cases.unfreeze_wallet import UnfreezeWalletUseCase
from backend.application.wallet.queries.get_wallet import GetWalletQuery
from backend.application.wallet.queries.get_my_wallets import GetMyWalletsQuery
from backend.application.wallet.queries.resolve_recipient import ResolveWalletRecipientQuery
from backend.application.wallet.dtos.filters import WalletFilter, WalletSortEnum

from backend.domain.share.enums import CurrencyEnum
from backend.domain.wallet.enums import WalletStatusEnum

from backend.infrastructure.wallet.number_generator import RandomWalletNumberGenerator

from backend.presentation.api.v1.dependencies.core import UowDep, ClockDep


def get_wallet_number_generator() -> RandomWalletNumberGenerator:
    return RandomWalletNumberGenerator()


WalletNumberGeneratorDep = Annotated[RandomWalletNumberGenerator, Depends(get_wallet_number_generator)]


def get_create_wallet_use_case(
        uow: UowDep,
        number_generator: WalletNumberGeneratorDep,
        clock: ClockDep
) -> CreateWalletUseCase:
    return CreateWalletUseCase(
        uow=uow,
        number_generator=number_generator,
        clock=clock
    )


def get_rename_wallet_use_case(
        uow: UowDep
) -> RenameWalletUseCase:
    return RenameWalletUseCase(
        uow=uow
    )


def get_close_wallet_use_case(
        uow: UowDep
) -> CloseWalletUseCase:
    return CloseWalletUseCase(
        uow=uow
    )


CreateWalletDep = Annotated[CreateWalletUseCase, Depends(get_create_wallet_use_case)]
RenameWalletDep = Annotated[RenameWalletUseCase, Depends(get_rename_wallet_use_case)]
CloseWalletDep = Annotated[CloseWalletUseCase, Depends(get_close_wallet_use_case)]


def get_freeze_wallet_use_case(
        uow: UowDep
) -> FreezeWalletUseCase:
    return FreezeWalletUseCase(uow=uow)


def get_unfreeze_wallet_use_case(
        uow: UowDep
) -> UnfreezeWalletUseCase:
    return UnfreezeWalletUseCase(uow=uow)


FreezeWalletDep = Annotated[FreezeWalletUseCase, Depends(get_freeze_wallet_use_case)]
UnfreezeWalletDep = Annotated[UnfreezeWalletUseCase, Depends(get_unfreeze_wallet_use_case)]


def get_wallet_query(
        uow: UowDep
) -> GetWalletQuery:
    return GetWalletQuery(
        uow=uow
    )


def get_my_wallets_query(
        uow: UowDep
) -> GetMyWalletsQuery:
    return GetMyWalletsQuery(
        uow=uow
    )


def get_wallet_filters(
        currency: CurrencyEnum | None = None,
        status: WalletStatusEnum | None = None,
        sort_by: WalletSortEnum = WalletSortEnum.created_at_asc
) -> WalletFilter:
    return WalletFilter(
        currency=currency,
        status=status,
        sort_by=sort_by
    )


GetWalletQueryDep = Annotated[GetWalletQuery, Depends(get_wallet_query)]
GetMyWalletsQueryDep = Annotated[GetMyWalletsQuery, Depends(get_my_wallets_query)]
WalletFilterDep = Annotated[WalletFilter, Depends(get_wallet_filters)]


def get_resolve_wallet_recipient_query(uow: UowDep) -> ResolveWalletRecipientQuery:
    return ResolveWalletRecipientQuery(uow=uow)


ResolveWalletRecipientDep = Annotated[ResolveWalletRecipientQuery, Depends(get_resolve_wallet_recipient_query)]
