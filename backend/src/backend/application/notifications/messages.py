from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from backend.application.share.messages import OutboxMessage
from backend.domain.user.value_objects import Email


@dataclass(frozen=True, kw_only=True)
class SendPasswordChangedNotification(OutboxMessage):
    """Notify the owner without including either the old or the new password."""

    user_id: UUID
    email: Email
    changed_at: datetime
