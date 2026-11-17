from uuid import UUID

from fastapi import APIRouter
from starlette import status

from backend.application.wallet.dtos.create_wallet import CreateWalletCommand
from backend.application.wallet.dtos.rename_wallet import RenameWalletCommand
from backend.application.wallet.dtos.close_wallet import CloseWalletCommand
from backend.application.wallet.dtos.freeze_wallet import FreezeWalletCommand
from backend.application.wallet.dtos.unfreeze_wallet import UnfreezeWalletCommand
from backend.application.wallet.dtos.get_wallet import GetWalletCommand
from backend.application.wallet.dtos.get_my_wallets import GetMyWalletsCommand

from backend.domain.wallet.value_objects import WalletName

from backend.presentation.api.v1.dependencies.security import CurrentActiveUserIdDep, CurrentUserIdDep
from backend.presentation.api.v1.dependencies.wallet import (
    CreateWalletDep,
    RenameWalletDep,
    CloseWalletDep,
    FreezeWalletDep,
    UnfreezeWalletDep,
    GetWalletQueryDep,
    GetMyWalletsQueryDep,
    WalletFilterDep
)
from backend.presentation.api.v1.schemas.errors import ErrorResponse
from backend.presentation.api.v1.schemas.wallet import (
    CreateWalletSchema,
    CreateWalletResponse,
    RenameWalletSchema,
    WalletResponse
)
from backend.application.wallet.dtos.get_wallet_balance import GetWalletBalanceCommand
from backend.application.wallet.dtos.get_wallet_transactions import GetWalletTransactionsCommand
from backend.presentation.api.v1.dependencies.finance import (
    GetWalletBalanceQueryDep, GetWalletTransactionsQueryDep, WalletTransactionFilterDep, PageLimit,
)
from backend.presentation.api.v1.schemas.finance import WalletBalanceResponse, WalletTransactionResponse, PageResponse

router = APIRouter(
    prefix="/wallets",
    tags=["wallet"],
)


@router.get(
    "",
    response_model=list[WalletResponse],
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorResponse, "description": "Missing, invalid or expired access token"},
        403: {"model": ErrorResponse, "description": "Inactive user"},
        404: {"model": ErrorResponse, "description": "User not found"},
        422: {"model": ErrorResponse, "description": "Invalid wallet filters"},
        500: {"model": ErrorResponse, "description": "Wallet accounting state is inconsistent"},
    },
)
async def get_wallets(
        current_user_id: CurrentUserIdDep,
        filters: WalletFilterDep,
        query: GetMyWalletsQueryDep
):
    cmd = GetMyWalletsCommand(
        user_id=current_user_id,
        filters=filters
    )
    result = await query.execute(cmd=cmd)
    return result


@router.get(
    "/{wallet_id}",
    response_model=WalletResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorResponse, "description": "Missing, invalid or expired access token"},
        403: {"model": ErrorResponse, "description": "Inactive user"},
        404: {"model": ErrorResponse, "description": "User or wallet not found"},
        422: {"model": ErrorResponse, "description": "Invalid wallet identifier"},
        500: {"model": ErrorResponse, "description": "Wallet accounting state is inconsistent"},
    },
)
async def get_wallet(
        wallet_id: UUID,
        current_user_id: CurrentUserIdDep,
        query: GetWalletQueryDep
):
    cmd = GetWalletCommand(
        user_id=current_user_id,
        wallet_id=wallet_id
    )
    result = await query.execute(cmd=cmd)
    return result


@router.get('/{wallet_id}/balance', response_model=WalletBalanceResponse,
            responses={code: {'model': ErrorResponse} for code in (401, 403, 404, 422, 500)})
async def get_wallet_balance(
        wallet_id: UUID,
        current_user_id: CurrentUserIdDep,
        query: GetWalletBalanceQueryDep,
):
    cmd = GetWalletBalanceCommand(user_id=current_user_id, wallet_id=wallet_id)
    result = await query.execute(cmd=cmd)
    return result


@router.get('/{wallet_id}/transactions', response_model=PageResponse[WalletTransactionResponse],
            responses={code: {'model': ErrorResponse} for code in (401, 403, 404, 422)})
async def get_wallet_transactions(
        wallet_id: UUID,
        current_user_id: CurrentUserIdDep,
        filters: WalletTransactionFilterDep,
        query: GetWalletTransactionsQueryDep,
        limit: PageLimit = 20,
        cursor: str | None = None,
):
    cmd = GetWalletTransactionsCommand(user_id=current_user_id, wallet_id=wallet_id, filters=filters, limit=limit, cursor=cursor)
    result = await query.execute(cmd=cmd)
    return result


@router.post(
    "",
    response_model=CreateWalletResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"model": ErrorResponse, "description": "Missing, invalid or expired access token"},
        403: {"model": ErrorResponse, "description": "Inactive user"},
        404: {"model": ErrorResponse, "description": "User not found"},
        422: {"model": ErrorResponse, "description": "Invalid request or wallet name"},
        503: {"model": ErrorResponse, "description": "Could not allocate a unique wallet number"},
    },
)
async def create_wallet(
        body: CreateWalletSchema,
        current_user_id: CurrentActiveUserIdDep,
        uc: CreateWalletDep
):
    cmd = CreateWalletCommand(
        user_id=current_user_id,
        name=WalletName(
            value=body.name
        ),
        currency=body.currency
    )
    result = await uc.execute(cmd=cmd)
    return result


@router.post(
    "/{wallet_id}/close",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses={
        401: {"model": ErrorResponse, "description": "Missing, invalid or expired access token"},
        403: {"model": ErrorResponse, "description": "Inactive user"},
        404: {"model": ErrorResponse, "description": "User or wallet not found"},
        409: {"model": ErrorResponse, "description": "Wallet balance is not zero"},
        422: {"model": ErrorResponse, "description": "Invalid wallet identifier"},
        500: {"model": ErrorResponse, "description": "Wallet accounting state is inconsistent"},
    },
)
async def close_wallet(
        wallet_id: UUID,
        current_user_id: CurrentActiveUserIdDep,
        uc: CloseWalletDep
):
    cmd = CloseWalletCommand(
        user_id=current_user_id,
        wallet_id=wallet_id
    )
    await uc.execute(cmd=cmd)


@router.post(
    "/{wallet_id}/freeze",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses={
        401: {"model": ErrorResponse, "description": "Missing, invalid or expired access token"},
        403: {"model": ErrorResponse, "description": "Inactive user"},
        404: {"model": ErrorResponse, "description": "User or wallet not found"},
        409: {"model": ErrorResponse, "description": "Wallet is closed"},
        422: {"model": ErrorResponse, "description": "Invalid wallet identifier"},
        500: {"model": ErrorResponse, "description": "Wallet accounting state is inconsistent"},
    },
)
async def freeze_wallet(
        wallet_id: UUID,
        current_user_id: CurrentActiveUserIdDep,
        uc: FreezeWalletDep
):
    cmd = FreezeWalletCommand(user_id=current_user_id, wallet_id=wallet_id)
    await uc.execute(cmd=cmd)


@router.post(
    "/{wallet_id}/unfreeze",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses={
        401: {"model": ErrorResponse, "description": "Missing, invalid or expired access token"},
        403: {"model": ErrorResponse, "description": "Inactive user"},
        404: {"model": ErrorResponse, "description": "User or wallet not found"},
        409: {"model": ErrorResponse, "description": "Wallet is closed"},
        422: {"model": ErrorResponse, "description": "Invalid wallet identifier"},
        500: {"model": ErrorResponse, "description": "Wallet accounting state is inconsistent"},
    },
)
async def unfreeze_wallet(
        wallet_id: UUID,
        current_user_id: CurrentActiveUserIdDep,
        uc: UnfreezeWalletDep
):
    cmd = UnfreezeWalletCommand(user_id=current_user_id, wallet_id=wallet_id)
    await uc.execute(cmd=cmd)


@router.patch(
    "/{wallet_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses={
        401: {"model": ErrorResponse, "description": "Missing, invalid or expired access token"},
        403: {"model": ErrorResponse, "description": "Inactive user"},
        404: {"model": ErrorResponse, "description": "User or wallet not found"},
        409: {"model": ErrorResponse, "description": "Wallet is closed"},
        422: {"model": ErrorResponse, "description": "Invalid request or wallet identifier"},
    },
)
async def update_wallet(
        wallet_id: UUID,
        body: RenameWalletSchema,
        current_user_id: CurrentActiveUserIdDep,
        uc: RenameWalletDep
):
    cmd = RenameWalletCommand(
        user_id=current_user_id,
        wallet_id=wallet_id,
        name=WalletName(
            value=body.name
        )
    )
    await uc.execute(cmd=cmd)
