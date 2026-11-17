from typing import Protocol

from backend.domain.share.events import Event


class IEventBus(Protocol):
    async def publish(self, event: Event) -> None:
        pass
