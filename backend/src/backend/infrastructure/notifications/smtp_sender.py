from email.message import EmailMessage

import aiosmtplib
from aiosmtplib.errors import SMTPException, SMTPResponseException, SMTPRecipientsRefused

from backend.application.notifications.dtos.email import OutgoingEmail
from backend.application.notifications.errors import PermanentDeliveryError, TransientDeliveryError
from backend.application.notifications.interfaces.email_sender import IEmailSender
from backend.infrastructure.notifications.settings import SmtpSettings


class SmtpEmailSender(IEmailSender):
    def __init__(self, settings: SmtpSettings):
        self._settings = settings

    async def send(self, email: OutgoingEmail) -> None:
        message = EmailMessage()
        message["From"] = str(self._settings.smtp_from_email)
        message["To"] = email.recipient.value
        message["Subject"] = email.subject
        message["Message-ID"] = email.message_id
        message.set_content(email.text)
        message.add_alternative(email.html, subtype="html")
        try:
            refused, _ = await aiosmtplib.send(
                message,
                hostname=self._settings.smtp_host,
                port=self._settings.smtp_port,
                username=self._settings.smtp_username.get_secret_value() if self._settings.smtp_username else None,
                password=self._settings.smtp_password.get_secret_value() if self._settings.smtp_password else None,
                use_tls=self._settings.smtp_security == "tls",
                start_tls=self._settings.smtp_security == "starttls",
                validate_certs=True,
                timeout=self._settings.smtp_timeout,
            )
            if refused:
                raise TransientDeliveryError()
        except SMTPRecipientsRefused as exc:
            if any(400 <= recipient.code < 500 for recipient in exc.recipients):
                raise TransientDeliveryError() from None
            raise PermanentDeliveryError() from None
        except SMTPResponseException as exc:
            if 400 <= exc.code < 500:
                raise TransientDeliveryError() from None
            raise PermanentDeliveryError() from None
        except (SMTPException, OSError, TimeoutError):
            raise TransientDeliveryError() from None
