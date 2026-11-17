from datetime import timedelta

from backend.presentation.api.v1.dependencies.client import ClientInfoDep
from backend.presentation.api.v1.dependencies.core import SettingsDep
from backend.presentation.api.v1.dependencies.rate_limit import RateLimiterDep, check_rate_limit
from backend.presentation.api.v1.dependencies.security import CurrentUserIdDep


async def limit_recipient_lookup(
        current_user_id: CurrentUserIdDep,
        client_info: ClientInfoDep,
        limiter: RateLimiterDep,
        settings: SettingsDep,
) -> None:
    check_rate_limit(await limiter.consume(
        f'recipient-lookup-ip:{client_info.ip_address}',
        limit=settings.recipient_lookup_rate_limit_ip_per_minute, window=timedelta(minutes=1),
    ))
    check_rate_limit(await limiter.consume(
        f'recipient-lookup-user:{current_user_id}',
        limit=settings.recipient_lookup_rate_limit_user_per_minute, window=timedelta(minutes=1),
    ))
