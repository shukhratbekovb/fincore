from typing import Annotated

from fastapi import Depends

from backend.application.auth.use_cases.change_password import ChangePasswordUseCase
from backend.application.auth.use_cases.request_password_reset import RequestPasswordResetUseCase
from backend.application.auth.use_cases.confirm_password_reset import ConfirmPasswordResetUseCase
from backend.application.auth.use_cases.confirm import ConfirmUserUseCase
from backend.application.auth.use_cases.login import LoginUserUseCase
from backend.application.auth.use_cases.logout import LogoutUserUseCase
from backend.application.auth.use_cases.refresh import RefreshSessionUseCase
from backend.application.auth.use_cases.register import RegisterUserUseCase
from backend.application.auth.use_cases.resend_confirmation import ResendRegistrationConfirmationUseCase

from backend.infrastructure.security.password_hasher import Argon2PasswordHasher
from backend.infrastructure.security.password_generator import PasswordGenerator
from backend.infrastructure.security.token_generator import TokenGenerator
from backend.infrastructure.security.token_hasher import TokenHasher
from backend.infrastructure.security.token_issuer import JWTTokenIssuer

from backend.presentation.api.v1.dependencies.core import SettingsDep, UowDep, ClockDep


def get_token_generator() -> TokenGenerator:
    return TokenGenerator()


def get_token_hasher() -> TokenHasher:
    return TokenHasher()


def get_password_hasher() -> Argon2PasswordHasher:
    return Argon2PasswordHasher()


def get_password_generator() -> PasswordGenerator:
    return PasswordGenerator()


def get_token_issuer(
        settings: SettingsDep
) -> JWTTokenIssuer:
    return JWTTokenIssuer(settings=settings)


TokenGeneratorDep = Annotated[TokenGenerator, Depends(get_token_generator)]
TokenHasherDep = Annotated[TokenHasher, Depends(get_token_hasher)]
TokenIssuerDep = Annotated[JWTTokenIssuer, Depends(get_token_issuer)]
PasswordHasherDep = Annotated[Argon2PasswordHasher, Depends(get_password_hasher)]
PasswordGeneratorDep = Annotated[PasswordGenerator, Depends(get_password_generator)]


def get_register_use_case(
        uow: UowDep,
        token_generator: TokenGeneratorDep,
        token_hasher: TokenHasherDep,
        clock: ClockDep,
        settings: SettingsDep
) -> RegisterUserUseCase:
    return RegisterUserUseCase(
        uow=uow,
        token_generator=token_generator,
        token_hasher=token_hasher,
        clock=clock,
        confirmation_ttl=settings.verification_confirmation_ttl
    )


def get_login_use_case(
        uow: UowDep,
        password_hasher: PasswordHasherDep,
        token_issuer: TokenIssuerDep,
        token_generator: TokenGeneratorDep,
        token_hasher: TokenHasherDep,
        clock: ClockDep,
        settings: SettingsDep
) -> LoginUserUseCase:
    return LoginUserUseCase(
        uow=uow,
        password_hasher=password_hasher,
        token_issuer=token_issuer,
        token_generator=token_generator,
        token_hasher=token_hasher,
        clock=clock,
        session_ttl=settings.session_ttl,
    )


def get_logout_use_case(
        uow: UowDep,
        token_hasher: TokenHasherDep,
        clock: ClockDep
) -> LogoutUserUseCase:
    return LogoutUserUseCase(
        uow=uow,
        token_hasher=token_hasher,
        clock=clock
    )


def get_refresh_use_case(
        uow: UowDep,
        token_issuer: TokenIssuerDep,
        token_generator: TokenGeneratorDep,
        token_hasher: TokenHasherDep,
        clock: ClockDep,
        settings: SettingsDep
) -> RefreshSessionUseCase:
    return RefreshSessionUseCase(
        uow=uow,
        token_issuer=token_issuer,
        token_generator=token_generator,
        token_hasher=token_hasher,
        clock=clock,
        session_ttl=settings.session_ttl
    )


def get_confirm_use_case(
        uow: UowDep,
        password_hasher: PasswordHasherDep,
        token_hasher: TokenHasherDep,
        clock: ClockDep
) -> ConfirmUserUseCase:
    return ConfirmUserUseCase(
        uow=uow,
        password_hasher=password_hasher,
        token_hasher=token_hasher,
        clock=clock
    )


def get_change_password_use_case(
        uow: UowDep,
        password_hasher: PasswordHasherDep,
        clock: ClockDep
) -> ChangePasswordUseCase:
    return ChangePasswordUseCase(
        uow=uow,
        password_hasher=password_hasher,
        clock=clock
    )


RegisterUserDep = Annotated[RegisterUserUseCase, Depends(get_register_use_case)]
LoginUserDep = Annotated[LoginUserUseCase, Depends(get_login_use_case)]
LogoutUserDep = Annotated[LogoutUserUseCase, Depends(get_logout_use_case)]
RefreshSessionDep = Annotated[RefreshSessionUseCase, Depends(get_refresh_use_case)]
ConfirmUserDep = Annotated[ConfirmUserUseCase, Depends(get_confirm_use_case)]
ChangePasswordDep = Annotated[ChangePasswordUseCase, Depends(get_change_password_use_case)]


def get_request_password_reset_use_case(
        uow: UowDep, token_generator: TokenGeneratorDep, token_hasher: TokenHasherDep,
        clock: ClockDep, settings: SettingsDep,
) -> RequestPasswordResetUseCase:
    return RequestPasswordResetUseCase(
        uow=uow, token_generator=token_generator, token_hasher=token_hasher,
        clock=clock, reset_ttl=settings.password_reset_ttl,
    )


def get_confirm_password_reset_use_case(
        uow: UowDep, password_generator: PasswordGeneratorDep, password_hasher: PasswordHasherDep,
        token_hasher: TokenHasherDep, clock: ClockDep,
) -> ConfirmPasswordResetUseCase:
    return ConfirmPasswordResetUseCase(
        uow=uow, password_generator=password_generator, password_hasher=password_hasher,
        token_hasher=token_hasher, clock=clock,
    )


RequestPasswordResetDep = Annotated[RequestPasswordResetUseCase, Depends(get_request_password_reset_use_case)]
ConfirmPasswordResetDep = Annotated[ConfirmPasswordResetUseCase, Depends(get_confirm_password_reset_use_case)]


def get_resend_confirmation_use_case(
        uow: UowDep, token_generator: TokenGeneratorDep, token_hasher: TokenHasherDep,
        clock: ClockDep, settings: SettingsDep,
) -> ResendRegistrationConfirmationUseCase:
    return ResendRegistrationConfirmationUseCase(
        uow=uow, token_generator=token_generator, token_hasher=token_hasher,
        clock=clock, confirmation_ttl=settings.verification_confirmation_ttl,
    )


ResendConfirmationDep = Annotated[
    ResendRegistrationConfirmationUseCase, Depends(get_resend_confirmation_use_case),
]
