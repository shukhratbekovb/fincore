from uuid import UUID

from fastapi import APIRouter
from starlette import status

from backend.application.session.dtos.remove_session import RemoveSessionCommand

from backend.presentation.api.v1.dependencies.security import CurrentUserIdDep
from backend.presentation.api.v1.dependencies.user import (
    CurrentUserQueryDep,
    ActiveSessionsQueryDep,
    RemoveAllSessionsDep,
    RemoveSessionDep
)
from backend.presentation.api.v1.schemas.errors import ErrorResponse
from backend.presentation.api.v1.schemas.user import UserResponse, SessionResponse
from backend.application.history.dtos.get_my_transactions import GetMyTransactionsCommand
from backend.application.wallet.dtos.get_my_balance_summary import GetMyBalanceSummaryCommand
from backend.domain.share.enums import CurrencyEnum
from backend.presentation.api.v1.dependencies.finance import (
    GetMyTransactionsQueryDep, MyTransactionsFilterDep, GetMyBalanceSummaryQueryDep, PageLimit,
)
from backend.presentation.api.v1.schemas.finance import TransactionResponse, PageResponse, BalanceSummaryResponse

router = APIRouter(
    prefix="/users",
    tags=["users"],
)


@router.get('/me/transactions', response_model=PageResponse[TransactionResponse],
            responses={code: {'model': ErrorResponse} for code in (401, 403, 404, 422)})
async def get_my_transactions(
        current_user_id: CurrentUserIdDep,
        filters: MyTransactionsFilterDep,
        query: GetMyTransactionsQueryDep,
        limit: PageLimit = 20,
        cursor: str | None = None,
):
    cmd = GetMyTransactionsCommand(user_id=current_user_id, filters=filters, limit=limit, cursor=cursor)
    result = await query.execute(cmd=cmd)
    return result


@router.get('/me/balances', response_model=BalanceSummaryResponse,
            responses={code: {'model': ErrorResponse} for code in (401, 403, 404, 422, 500)})
async def get_my_balance_summary(
        current_user_id: CurrentUserIdDep,
        query: GetMyBalanceSummaryQueryDep,
        currency: CurrencyEnum | None = None,
):
    cmd = GetMyBalanceSummaryCommand(user_id=current_user_id, currency=currency)
    result = await query.execute(cmd=cmd)
    return result


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorResponse, "description": "Missing, invalid or expired access token"},
        403: {"model": ErrorResponse, "description": "Inactive user"},
        404: {"model": ErrorResponse, "description": "User not found"},
    },
)
async def get_me(
        current_user_id: CurrentUserIdDep,
        query: CurrentUserQueryDep
):
    result = await query.execute(user_id=current_user_id)
    return UserResponse(
        id=result.id,
        username=result.username.value,
        email=result.email.value,
        created_at=result.created_at
    )


@router.get(
    "/me/sessions",
    response_model=list[SessionResponse],
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorResponse, "description": "Missing, invalid or expired access token"},
        403: {"model": ErrorResponse, "description": "Inactive user"},
        404: {"model": ErrorResponse, "description": "User not found"},
    },
)
async def get_active_sessions(
        current_user_id: CurrentUserIdDep,
        query: ActiveSessionsQueryDep
):
    result = await query.execute(user_id=current_user_id)
    return result


@router.delete(
    "/me/sessions",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses={
        401: {"model": ErrorResponse, "description": "Missing, invalid or expired access token"},
        403: {"model": ErrorResponse, "description": "Inactive user"},
        404: {"model": ErrorResponse, "description": "User not found"},
    },
)
async def delete_all_active_sessions(
        current_user_id: CurrentUserIdDep,
        uc: RemoveAllSessionsDep
):
    await uc.execute(user_id=current_user_id)


@router.delete(
    "/me/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses={
        401: {"model": ErrorResponse, "description": "Missing, invalid or expired access token"},
        403: {"model": ErrorResponse, "description": "Inactive user"},
        404: {"model": ErrorResponse, "description": "User or session not found"},
        422: {"model": ErrorResponse, "description": "Invalid session identifier"},
    },
)
async def delete_session(
        session_id: UUID,
        current_user_id: CurrentUserIdDep,
        uc: RemoveSessionDep
):
    cmd = RemoveSessionCommand(
        user_id=current_user_id,
        session_id=session_id
    )
    await uc.execute(cmd=cmd)
