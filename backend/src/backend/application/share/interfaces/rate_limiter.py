from datetime import timedelta
from typing import Protocol


class IRateLimiter(Protocol):
    async def consume(self, key: str, *, limit: int, window: timedelta) -> int:
        """Consume atomically across instances; return 0 or retry seconds.

        Raise RateLimiterUnavailableError when the budget cannot be checked.
        """
        ...
