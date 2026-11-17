from typing import Protocol

from backend.application.share.messages import OutboxMessage


class IOutbox(Protocol):
    async def add(self, message: OutboxMessage) -> None:
        """Persist with the UoW transaction; never send directly."""
        ...
