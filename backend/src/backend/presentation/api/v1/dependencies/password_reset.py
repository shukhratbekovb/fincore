from datetime import timedelta

from backend.presentation.api.v1.dependencies.rate_limit import RateLimiterDep, check_rate_limit
from backend.presentation.api.v1.dependencies.client import ClientInfoDep
from backend.presentation.api.v1.schemas.auth import RequestPasswordResetSchema


async def limit_password_reset_request(
        body: RequestPasswordResetSchema, client_info: ClientInfoDep, limiter: RateLimiterDep,
) -> None:
    check_rate_limit(await limiter.consume(
        f"reset-request-ip:{client_info.ip_address}", limit=10, window=timedelta(minutes=1),
    ))
    # The same budget is applied to eligible and unknown addresses.
    check_rate_limit(await limiter.consume(
        f"reset-request-email:{body.email.lower()}", limit=3, window=timedelta(minutes=15),
    ))


async def limit_password_reset_confirmation(client_info: ClientInfoDep, limiter: RateLimiterDep) -> None:
    check_rate_limit(await limiter.consume(
        f"reset-confirm-ip:{client_info.ip_address}", limit=20, window=timedelta(minutes=1),
    ))
