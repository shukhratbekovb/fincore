from dataclasses import dataclass, field

from backend.domain.user.value_objects import Email


@dataclass(frozen=True)
class OutgoingEmail:
    recipient: Email
    message_id: str
    subject: str
    text: str = field(repr=False)
    html: str = field(repr=False)
