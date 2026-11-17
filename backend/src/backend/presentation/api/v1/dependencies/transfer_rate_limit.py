from datetime import timedelta

from backend.presentation.api.v1.dependencies.client import ClientInfoDep
from backend.presentation.api.v1.dependencies.core import SettingsDep
from backend.presentation.api.v1.dependencies.finance import IdempotencyKeyDep
from backend.presentation.api.v1.dependencies.rate_limit import RateLimiterDep, check_rate_limit
from backend.presentation.api.v1.dependencies.security import CurrentUserIdDep


async def limit_transfer(
        current_user_id: CurrentUserIdDep,
        idempotency_key: IdempotencyKeyDep,
        client_info: ClientInfoDep,
        limiter: RateLimiterDep,
        settings: SettingsDep,
) -> None:
    # Validate JWT/header first. Idempotency does not exempt HTTP retries from limits.
    check_rate_limit(await limiter.consume(
        f'transfer-ip:{client_info.ip_address}',
        limit=settings.transfer_rate_limit_ip_per_minute, window=timedelta(minutes=1),
    ))
    check_rate_limit(await limiter.consume(
        f'transfer-user:{current_user_id}',
        limit=settings.transfer_rate_limit_user_per_minute, window=timedelta(minutes=1),
    ))
