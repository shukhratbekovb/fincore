from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from backend.application.share.messages import OutboxMessage
from backend.domain.user.value_objects import Email


@dataclass(frozen=True, kw_only=True)
class SendRegistrationConfirmation(OutboxMessage):
    """Restrict access to the secret token and exclude it from logs.

    Remove the secret payload from the outbox after successful delivery.
    """

    user_id: UUID
    email: Email
    token: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True, kw_only=True)
class SendPasswordResetConfirmation(OutboxMessage):
    """Deliver a one-time reset link. Remove the secret payload after delivery."""

    user_id: UUID
    email: Email
    token: str = field(repr=False)
    expires_at: datetime
