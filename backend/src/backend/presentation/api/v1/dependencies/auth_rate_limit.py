from datetime import timedelta

from backend.presentation.api.v1.dependencies.client import ClientInfoDep
from backend.presentation.api.v1.dependencies.core import SettingsDep
from backend.presentation.api.v1.dependencies.rate_limit import RateLimiterDep, check_rate_limit
from backend.presentation.api.v1.schemas.auth import (
    LoginUserSchema, RegisterUserSchema, ResendRegistrationConfirmationSchema,
)


async def limit_login(
        body: LoginUserSchema,
        client_info: ClientInfoDep,
        limiter: RateLimiterDep,
        settings: SettingsDep,
) -> None:
    check_rate_limit(await limiter.consume(
        f'login-ip:{client_info.ip_address}',
        limit=settings.login_rate_limit_ip_per_minute, window=timedelta(minutes=1),
    ))
    # Known and unknown usernames have identical budgets; match Username normalization.
    check_rate_limit(await limiter.consume(
        f'login-username:{body.username.lower()}',
        limit=settings.login_rate_limit_username_per_minute, window=timedelta(minutes=1),
    ))


async def limit_registration(
        body: RegisterUserSchema,
        client_info: ClientInfoDep,
        limiter: RateLimiterDep,
        settings: SettingsDep,
) -> None:
    check_rate_limit(await limiter.consume(
        f'register-ip:{client_info.ip_address}',
        limit=settings.register_rate_limit_ip_per_hour, window=timedelta(hours=1),
    ))
    check_rate_limit(await limiter.consume(
        f'register-email:{body.email.lower()}',
        limit=settings.register_rate_limit_email_per_hour, window=timedelta(hours=1),
    ))


async def limit_confirmation_resend(
        body: ResendRegistrationConfirmationSchema,
        client_info: ClientInfoDep,
        limiter: RateLimiterDep,
        settings: SettingsDep,
) -> None:
    check_rate_limit(await limiter.consume(
        f'confirmation-resend-ip:{client_info.ip_address}',
        limit=settings.resend_confirmation_rate_limit_ip_per_hour, window=timedelta(hours=1),
    ))
    check_rate_limit(await limiter.consume(
        f'confirmation-resend-email:{body.email.lower()}',
        limit=settings.resend_confirmation_rate_limit_email_per_hour, window=timedelta(hours=1),
    ))
