from datetime import timedelta
from typing import Literal, Protocol

from backend.application.outbox.dtos.delivery import OutboxDelivery


class IOutboxQueue(Protocol):
    async def claim(self, *, limit: int, lease: timedelta) -> list[OutboxDelivery]: ...

    async def finish(
            self, delivery: OutboxDelivery, *, status: Literal["sent", "failed", "expired"],
            error_code: str | None = None,
    ) -> bool: ...

    async def retry(self, delivery: OutboxDelivery, *, delay: timedelta, error_code: str) -> bool: ...
