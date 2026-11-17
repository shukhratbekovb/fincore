from fastapi import APIRouter

from backend.presentation.api.v1.routers.auth import router as auth_router
from backend.presentation.api.v1.routers.user import router as user_router
from backend.presentation.api.v1.routers.wallet import router as wallet_router
from backend.presentation.api.v1.routers.transfer import router as transfer_router
from backend.presentation.api.v1.routers.sandbox import router as sandbox_router
from backend.presentation.api.v1.routers.recipient import router as recipient_router

v1_router = APIRouter(
    prefix="/v1",
)

v1_router.include_router(auth_router)
v1_router.include_router(user_router)
v1_router.include_router(wallet_router)
v1_router.include_router(transfer_router)
v1_router.include_router(sandbox_router)
v1_router.include_router(recipient_router)
