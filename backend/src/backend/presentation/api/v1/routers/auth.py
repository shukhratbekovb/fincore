import asyncio
import secrets
import time

from fastapi import APIRouter, Depends
from starlette import status

from backend.application.auth.dtos.change_password import ChangePasswordCommand
from backend.application.auth.dtos.confirm import ConfirmUserCommand
from backend.application.auth.dtos.login import LoginUserCommand
from backend.application.auth.dtos.logout import LogoutUserCommand
from backend.application.auth.dtos.refresh import RefreshSessionCommand
from backend.application.auth.dtos.register import RegisterUserCommand
from backend.application.auth.dtos.resend_confirmation import ResendRegistrationConfirmationCommand
from backend.application.auth.dtos.password_reset import RequestPasswordResetCommand, ConfirmPasswordResetCommand

from backend.domain.user.value_objects import Username, RawPassword, PasswordCandidate, Email

from backend.presentation.api.v1.dependencies.client import ClientInfoDep
from backend.presentation.api.v1.dependencies.auth import (
    RegisterUserDep,
    LoginUserDep,
    LogoutUserDep,
    RefreshSessionDep,
    ConfirmUserDep,
    ChangePasswordDep,
    RequestPasswordResetDep,
    ConfirmPasswordResetDep,
    ResendConfirmationDep,
)
from backend.presentation.api.v1.dependencies.password_reset import (
    limit_password_reset_request, limit_password_reset_confirmation,
)
from backend.presentation.api.v1.dependencies.auth_rate_limit import (
    limit_login, limit_registration, limit_confirmation_resend,
)
from backend.presentation.api.v1.dependencies.rate_limit import RATE_LIMIT_RESPONSES
from backend.presentation.api.v1.dependencies.security import CurrentUserIdDep
from backend.presentation.api.v1.schemas.auth import (
    LoginUserSchema,
    TokenResponse,
    RegisterUserSchema,
    RegisterUserResponse,
    RefreshSessionSchema,
    LogoutUserSchema,
    ConfirmUserSchema,
    ChangePasswordSchema,
    RequestPasswordResetSchema,
    ConfirmPasswordResetSchema,
    PasswordResetRequestedResponse,
    PasswordResetResponse,
    ResendRegistrationConfirmationSchema,
    RegistrationConfirmationRequestedResponse,
)
from backend.presentation.api.v1.schemas.errors import ErrorResponse

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)


@router.post(
    "/login",
    dependencies=[Depends(limit_login)],
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    responses={
        **RATE_LIMIT_RESPONSES,
        400: {"model": ErrorResponse, "description": "Client IP unavailable"},
        401: {"model": ErrorResponse, "description": "Invalid credentials"},
        403: {"model": ErrorResponse, "description": "Inactive user"},
        422: {"model": ErrorResponse, "description": "Invalid request"},
    },
)
async def login(
        body: LoginUserSchema,
        client_info: ClientInfoDep,
        uc: LoginUserDep
):
    cmd = LoginUserCommand(
        username=Username(
            value=body.username,
        ),
        password=PasswordCandidate(
            value=body.password
        ),
        ip_address=client_info.ip_address,
        user_agent=client_info.user_agent,
    )
    result = await uc.execute(cmd=cmd)
    return result


@router.post(
    "/register",
    dependencies=[Depends(limit_registration)],
    status_code=status.HTTP_201_CREATED,
    response_model=RegisterUserResponse,
    responses={
        **RATE_LIMIT_RESPONSES,
        400: {"model": ErrorResponse, "description": "Client IP unavailable"},
        409: {"model": ErrorResponse, "description": "Email or username already registered"},
        422: {"model": ErrorResponse, "description": "Invalid request"},
    },
)
async def register(
        body: RegisterUserSchema,
        uc: RegisterUserDep
):
    cmd = RegisterUserCommand(
        username=Username(
            value=body.username
        ),
        email=Email(
            value=body.email
        )
    )
    result = await uc.execute(cmd=cmd)
    return result


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse, "description": "Client IP unavailable"},
        401: {"model": ErrorResponse, "description": "Invalid, expired or reused refresh token"},
        403: {"model": ErrorResponse, "description": "Inactive user"},
        422: {"model": ErrorResponse, "description": "Invalid request"},
    },
)
async def refresh(
        body: RefreshSessionSchema,
        client_info: ClientInfoDep,
        uc: RefreshSessionDep
):
    cmd = RefreshSessionCommand(
        refresh_token=body.refresh_token,
        ip_address=client_info.ip_address,
        user_agent=client_info.user_agent,
    )
    result = await uc.execute(cmd=cmd)
    return result


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses={422: {"model": ErrorResponse, "description": "Invalid request"}},
)
async def logout(
        body: LogoutUserSchema,
        uc: LogoutUserDep
):
    cmd = LogoutUserCommand(
        refresh_token=body.refresh_token
    )
    await uc.execute(cmd=cmd)


@router.post(
    "/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid, expired or used confirmation token"},
        404: {"model": ErrorResponse, "description": "User not found"},
        409: {"model": ErrorResponse, "description": "User is not awaiting confirmation"},
        422: {"model": ErrorResponse, "description": "Invalid request or new password"},
    },
)
async def confirm(
        body: ConfirmUserSchema,
        uc: ConfirmUserDep
):
    cmd = ConfirmUserCommand(
        token=body.token,
        password=RawPassword(
            value=body.password
        )
    )
    await uc.execute(cmd=cmd)


@router.post(
    "/confirm/resend",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RegistrationConfirmationRequestedResponse,
    dependencies=[Depends(limit_confirmation_resend)],
    responses={
        **RATE_LIMIT_RESPONSES,
        400: {"model": ErrorResponse, "description": "Client IP unavailable"},
        422: {"model": ErrorResponse, "description": "Invalid request"},
    },
)
async def resend_confirmation(
        body: ResendRegistrationConfirmationSchema, uc: ResendConfirmationDep,
):
    started = time.monotonic()
    await uc.execute(cmd=ResendRegistrationConfirmationCommand(email=Email(body.email)))
    # Reduce the fast ineligible-account path without promising constant timing.
    delay = 0.5 + secrets.randbelow(101) / 1000 - (time.monotonic() - started)
    if delay > 0:
        await asyncio.sleep(delay)
    return RegistrationConfirmationRequestedResponse(
        message="If the account is awaiting confirmation, a new confirmation email will be sent.",
    )


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses={
        401: {"model": ErrorResponse, "description": "Invalid credentials or access token"},
        403: {"model": ErrorResponse, "description": "Inactive user"},
        422: {"model": ErrorResponse, "description": "Invalid request or new password"},
    },
)
async def change_password(
        body: ChangePasswordSchema,
        uc: ChangePasswordDep,
        current_user_id: CurrentUserIdDep
):
    cmd = ChangePasswordCommand(
        current_password=RawPassword(
            value=body.current_password
        ),
        new_password=RawPassword(
            value=body.new_password
        ),
        user_id=current_user_id
    )

    await uc.execute(cmd=cmd)


@router.post(
    "/password-reset/request",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PasswordResetRequestedResponse,
    dependencies=[Depends(limit_password_reset_request)],
    responses={
        503: {"model": ErrorResponse, "description": "Request limit service unavailable"},
        400: {"model": ErrorResponse, "description": "Client IP unavailable"},
        422: {"model": ErrorResponse, "description": "Invalid request"},
        429: {"model": ErrorResponse, "description": "Too many requests", "headers": {
            "Retry-After": {"schema": {"type": "integer"}, "description": "Seconds before retry"},
        }},
    },
)
async def request_password_reset(body: RequestPasswordResetSchema, uc: RequestPasswordResetDep):
    started = time.monotonic()
    await uc.execute(cmd=RequestPasswordResetCommand(email=Email(body.email)))
    # Reduce the fast unknown-account path; this is not a constant-time guarantee.
    delay = 0.5 + secrets.randbelow(101) / 1000 - (time.monotonic() - started)
    if delay > 0:
        await asyncio.sleep(delay)
    return PasswordResetRequestedResponse(
        message="If the account is eligible, a password reset email will be sent.",
    )


@router.post(
    "/password-reset/confirm",
    response_model=PasswordResetResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(limit_password_reset_confirmation)],
    responses={
        503: {"model": ErrorResponse, "description": "Request limit service unavailable"},
        400: {"model": ErrorResponse, "description": "Invalid reset token or client IP unavailable"},
        422: {"model": ErrorResponse, "description": "Invalid request"},
        429: {"model": ErrorResponse, "description": "Too many requests", "headers": {
            "Retry-After": {"schema": {"type": "integer"}, "description": "Seconds before retry"},
        }},
    },
)
async def confirm_password_reset(body: ConfirmPasswordResetSchema, uc: ConfirmPasswordResetDep):
    return await uc.execute(cmd=ConfirmPasswordResetCommand(token=body.token))
