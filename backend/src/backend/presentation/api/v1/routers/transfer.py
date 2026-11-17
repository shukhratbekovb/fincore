from uuid import UUID

from fastapi import APIRouter, Depends

from backend.application.transfer.dtos.create_transfer import CreateTransferCommand
from backend.application.transfer.dtos.get_transfer import GetTransferCommand
from backend.application.transfer.dtos.get_my_transfers import GetMyTransfersCommand
from backend.presentation.api.v1.dependencies.security import CurrentUserIdDep
from backend.presentation.api.v1.dependencies.finance import (
    CreateTransferDep, GetTransferQueryDep, GetMyTransfersQueryDep, TransferFilterDep, IdempotencyKeyDep, PageLimit,
)
from backend.presentation.api.v1.schemas.finance import CreateTransferSchema, CreateTransferResponse, TransferResponse, PageResponse
from backend.presentation.api.v1.schemas.errors import ErrorResponse
from backend.presentation.api.v1.dependencies.rate_limit import RATE_LIMIT_RESPONSES
from backend.presentation.api.v1.dependencies.transfer_rate_limit import limit_transfer

READ_ERRORS = {code: {'model': ErrorResponse} for code in (401, 403, 404, 422)}
WRITE_ERRORS = {code: {'model': ErrorResponse} for code in (401, 403, 404, 409, 422, 500)}
router = APIRouter(prefix='/transfers', tags=['transfers'])


@router.post(
    '', response_model=CreateTransferResponse, status_code=201,
    dependencies=[Depends(limit_transfer)],
    responses={**WRITE_ERRORS, **RATE_LIMIT_RESPONSES, 400: {'model': ErrorResponse, 'description': 'Client IP unavailable'}},
)
async def create_transfer(
        body: CreateTransferSchema,
        current_user_id: CurrentUserIdDep,
        idempotency_key: IdempotencyKeyDep,
        uc: CreateTransferDep,
):
    cmd = CreateTransferCommand(
        user_id=current_user_id, sender_wallet_id=body.sender_wallet_id,
        receiver_wallet_id=body.receiver_wallet_id, amount_minor=body.amount_minor,
        currency=body.currency, idempotency_key=idempotency_key,
    )
    result = await uc.execute(cmd=cmd)
    return result


@router.get('', response_model=PageResponse[TransferResponse], responses=READ_ERRORS)
async def get_my_transfers(
        current_user_id: CurrentUserIdDep,
        filters: TransferFilterDep,
        query: GetMyTransfersQueryDep,
        limit: PageLimit = 20,
        cursor: str | None = None,
):
    cmd = GetMyTransfersCommand(user_id=current_user_id, filters=filters, limit=limit, cursor=cursor)
    result = await query.execute(cmd=cmd)
    return result


@router.get('/{transfer_id}', response_model=TransferResponse, responses=READ_ERRORS)
async def get_transfer(
        transfer_id: UUID,
        current_user_id: CurrentUserIdDep,
        query: GetTransferQueryDep,
):
    cmd = GetTransferCommand(user_id=current_user_id, transfer_id=transfer_id)
    result = await query.execute(cmd=cmd)
    return result
