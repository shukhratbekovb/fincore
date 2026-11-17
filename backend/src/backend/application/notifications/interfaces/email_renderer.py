from datetime import datetime
from typing import Protocol

from backend.application.notifications.dtos.email import OutgoingEmail
from backend.domain.user.value_objects import Email


class IEmailRenderer(Protocol):
    def registration_confirmation(
            self, *, recipient: Email, message_id: str, confirmation_url: str, expires_at: datetime,
    ) -> OutgoingEmail: ...

    def password_reset_confirmation(
            self, *, recipient: Email, message_id: str, confirmation_url: str, expires_at: datetime,
    ) -> OutgoingEmail: ...

    def password_changed(
            self, *, recipient: Email, message_id: str, changed_at: datetime,
    ) -> OutgoingEmail: ...
