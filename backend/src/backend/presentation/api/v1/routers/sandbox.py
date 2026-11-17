from fastapi import APIRouter

from backend.application.sandbox_top_up.dtos.create_top_up import CreateSandboxTopUpCommand
from backend.presentation.api.v1.dependencies.security import CurrentUserIdDep
from backend.presentation.api.v1.dependencies.finance import CreateSandboxTopUpDep, IdempotencyKeyDep
from backend.presentation.api.v1.schemas.finance import CreateSandboxTopUpSchema, CreateSandboxTopUpResponse
from backend.presentation.api.v1.routers.transfer import WRITE_ERRORS

router = APIRouter(prefix='/sandbox', tags=['sandbox'])


@router.post('/top-ups', response_model=CreateSandboxTopUpResponse, status_code=201, responses=WRITE_ERRORS)
async def create_sandbox_top_up(
        body: CreateSandboxTopUpSchema,
        current_user_id: CurrentUserIdDep,
        idempotency_key: IdempotencyKeyDep,
        uc: CreateSandboxTopUpDep,
):
    cmd = CreateSandboxTopUpCommand(
        user_id=current_user_id, wallet_id=body.wallet_id, amount_minor=body.amount_minor,
        currency=body.currency, idempotency_key=idempotency_key,
    )
    result = await uc.execute(cmd=cmd)
    return result
