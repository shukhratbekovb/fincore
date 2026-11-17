from dataclasses import dataclass
from urllib.parse import urlencode

from backend.application.notifications.errors import DeliveryExpiredError, PermanentDeliveryError
from backend.application.notifications.interfaces.email_renderer import IEmailRenderer
from backend.application.notifications.interfaces.email_sender import IEmailSender
from backend.application.share.interfaces.clock import IClock
from backend.application.share.messages import OutboxMessage
from backend.application.verification.messages import SendPasswordResetConfirmation


@dataclass(frozen=True)
class SendPasswordResetConfirmationHandler:
    sender: IEmailSender
    renderer: IEmailRenderer
    clock: IClock
    confirmation_url: str
    message_id_domain: str

    async def execute(self, message: OutboxMessage) -> None:
        if not isinstance(message, SendPasswordResetConfirmation):
            raise PermanentDeliveryError()
        if message.expires_at.tzinfo is None or message.expires_at.utcoffset() is None:
            raise PermanentDeliveryError()
        if self.clock.now() >= message.expires_at:
            raise DeliveryExpiredError()
        email = self.renderer.password_reset_confirmation(
            recipient=message.email,
            message_id=f"<{message.id}@{self.message_id_domain}>",
            confirmation_url=self.confirmation_url + "#" + urlencode({"token": message.token}),
            expires_at=message.expires_at,
        )
        await self.sender.send(email)
