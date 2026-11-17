from fastapi import APIRouter, Depends

from backend.application.wallet.dtos.resolve_recipient import ResolveWalletRecipientCommand
from backend.domain.wallet.value_objects import WalletNumber
from backend.presentation.api.v1.dependencies.rate_limit import RATE_LIMIT_RESPONSES
from backend.presentation.api.v1.dependencies.recipient_rate_limit import limit_recipient_lookup
from backend.presentation.api.v1.dependencies.security import CurrentUserIdDep
from backend.presentation.api.v1.dependencies.wallet import ResolveWalletRecipientDep
from backend.presentation.api.v1.schemas.errors import ErrorResponse
from backend.presentation.api.v1.schemas.wallet import ResolveWalletRecipientSchema, WalletRecipientResponse


router = APIRouter(prefix='/transfer-recipients', tags=['wallet'])


@router.post('/resolve', response_model=WalletRecipientResponse,
             dependencies=[Depends(limit_recipient_lookup)],
             responses={**RATE_LIMIT_RESPONSES, **{code: {'model': ErrorResponse} for code in (400, 401, 403, 404, 422)}})
async def resolve_wallet_recipient(
        body: ResolveWalletRecipientSchema,
        current_user_id: CurrentUserIdDep,
        query: ResolveWalletRecipientDep,
):
    return await query.execute(ResolveWalletRecipientCommand(
        user_id=current_user_id, wallet_number=WalletNumber(body.wallet_number),
    ))
