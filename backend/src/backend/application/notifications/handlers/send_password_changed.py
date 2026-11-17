from dataclasses import dataclass

from backend.application.notifications.errors import PermanentDeliveryError
from backend.application.notifications.interfaces.email_renderer import IEmailRenderer
from backend.application.notifications.interfaces.email_sender import IEmailSender
from backend.application.notifications.messages import SendPasswordChangedNotification
from backend.application.share.messages import OutboxMessage


@dataclass(frozen=True)
class SendPasswordChangedNotificationHandler:
    sender: IEmailSender
    renderer: IEmailRenderer
    message_id_domain: str

    async def execute(self, message: OutboxMessage) -> None:
        if not isinstance(message, SendPasswordChangedNotification):
            raise PermanentDeliveryError()
        if message.changed_at.tzinfo is None or message.changed_at.utcoffset() is None:
            raise PermanentDeliveryError()
        email = self.renderer.password_changed(
            recipient=message.email,
            message_id=f"<{message.id}@{self.message_id_domain}>",
            changed_at=message.changed_at,
        )
        await self.sender.send(email)
