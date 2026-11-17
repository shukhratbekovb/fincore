from datetime import datetime, timezone

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from backend.application.notifications.dtos.email import OutgoingEmail
from backend.application.notifications.interfaces.email_renderer import IEmailRenderer
from backend.domain.user.value_objects import Email


class JinjaEmailRenderer(IEmailRenderer):
    def __init__(self, locale: str = "ru"):
        if locale not in {"ru", "en"}:
            raise ValueError("Unsupported email locale")
        self._locale = locale
        self._environment = Environment(
            loader=PackageLoader("backend.infrastructure.notifications", "templates"),
            autoescape=select_autoescape(["html"]),
            undefined=StrictUndefined,
        )

    def registration_confirmation(
            self, *, recipient: Email, message_id: str, confirmation_url: str, expires_at: datetime,
    ) -> OutgoingEmail:
        context = {
            "confirmation_url": confirmation_url,
            "expires_at": expires_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }
        return self._render("registration_confirmation", recipient, message_id, context)

    def password_reset_confirmation(
            self, *, recipient: Email, message_id: str, confirmation_url: str, expires_at: datetime,
    ) -> OutgoingEmail:
        return self._render("password_reset_confirmation", recipient, message_id, {
            "confirmation_url": confirmation_url,
            "expires_at": expires_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        })

    def password_changed(
            self, *, recipient: Email, message_id: str, changed_at: datetime,
    ) -> OutgoingEmail:
        return self._render("password_changed", recipient, message_id, {
            "changed_at": changed_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        })

    def _render(self, template: str, recipient: Email, message_id: str, context: dict) -> OutgoingEmail:
        prefix = f"{template}/{self._locale}"
        return OutgoingEmail(
            recipient=recipient, message_id=message_id,
            subject=self._environment.get_template(f"{prefix}/subject.txt").render(context).strip(),
            text=self._environment.get_template(f"{prefix}/body.txt").render(context),
            html=self._environment.get_template(f"{prefix}/body.html").render(context),
        )
