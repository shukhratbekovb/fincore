from typing import Protocol

from backend.application.share.messages import OutboxMessage


class IOutboxHandler(Protocol):
    async def execute(self, message: OutboxMessage) -> None: ...
