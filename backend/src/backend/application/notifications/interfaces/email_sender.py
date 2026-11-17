from typing import Protocol

from backend.application.notifications.dtos.email import OutgoingEmail


class IEmailSender(Protocol):
    async def send(self, email: OutgoingEmail) -> None: ...
