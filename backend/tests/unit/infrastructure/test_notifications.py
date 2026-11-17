from unittest.mock import AsyncMock

import pytest
from aiosmtplib.errors import SMTPException, SMTPRecipientRefused, SMTPRecipientsRefused, SMTPResponseException
from pydantic import ValidationError

from backend.application.notifications.errors import PermanentDeliveryError, TransientDeliveryError
from backend.domain.user.value_objects import Email
from backend.infrastructure.notifications.jinja_renderer import JinjaEmailRenderer
from backend.infrastructure.notifications.settings import OutboxWorkerSettings, SmtpSettings
from backend.infrastructure.notifications.smtp_sender import SmtpEmailSender


@pytest.mark.parametrize('locale', ['ru', 'en'])
def test_renderer_outputs_text_html_and_escapes_url(now, locale):
    email = JinjaEmailRenderer(locale).registration_confirmation(
        recipient=Email('alice@example.com'), message_id='<id@example.com>',
        confirmation_url='https://app.example.com/confirm#token=<script>"&', expires_at=now,
    )
    assert email.subject and 'FinCore' in email.subject
    assert '<script>' not in email.html
    assert '&lt;script&gt;' in email.html
    assert '<script>' in email.text
    assert 'UTC' in email.text
    assert 'token=' not in repr(email)


def test_unsupported_template_locale():
    with pytest.raises(ValueError):
        JinjaEmailRenderer('de')


@pytest.mark.parametrize('security,port', [('none', 1025), ('starttls', 587), ('tls', 465)])
async def test_sender_builds_multipart_and_enforces_tls_mode(monkeypatch, now, security, port):
    smtp_send = AsyncMock(return_value=({}, 'OK'))
    monkeypatch.setattr('backend.infrastructure.notifications.smtp_sender.aiosmtplib.send', smtp_send)
    settings = SmtpSettings(_env_file=None, smtp_security=security, smtp_port=port, smtp_username='user', smtp_password='password')
    email = JinjaEmailRenderer().registration_confirmation(recipient=Email('alice@example.com'), message_id='<id@example.com>', confirmation_url='https://app.example.com/#token=secret', expires_at=now)
    await SmtpEmailSender(settings).send(email)
    mime = smtp_send.call_args.args[0]
    assert mime['Message-ID'] == '<id@example.com>'
    assert mime.get_body(preferencelist=('plain',)).get_content().strip() == email.text.strip()
    assert mime.get_body(preferencelist=('html',)).get_content().strip() == email.html.strip()
    options = smtp_send.call_args.kwargs
    assert options['use_tls'] == (security == 'tls')
    assert options['start_tls'] == (security == 'starttls')
    assert options['validate_certs'] is True
    assert options['username'] == 'user'


@pytest.mark.parametrize('error,expected', [
    (SMTPResponseException(451, 'private response'), TransientDeliveryError),
    (SMTPResponseException(550, 'private response'), PermanentDeliveryError),
    (SMTPRecipientsRefused([SMTPRecipientRefused(450, 'private', 'alice@example.com')]), TransientDeliveryError),
    (SMTPRecipientsRefused([SMTPRecipientRefused(550, 'private', 'alice@example.com')]), PermanentDeliveryError),
    (SMTPException('private'), TransientDeliveryError),
    (OSError('private'), TransientDeliveryError),
    (TimeoutError('private'), TransientDeliveryError),
])
async def test_smtp_errors_are_classified_without_leaking_server_text(monkeypatch, now, error, expected):
    smtp_send = AsyncMock(side_effect=error)
    monkeypatch.setattr('backend.infrastructure.notifications.smtp_sender.aiosmtplib.send', smtp_send)
    email = JinjaEmailRenderer().registration_confirmation(recipient=Email('alice@example.com'), message_id='<id@example.com>', confirmation_url='https://app.example.com/', expires_at=now)
    with pytest.raises(expected) as exc:
        await SmtpEmailSender(SmtpSettings(_env_file=None)).send(email)
    assert 'private' not in str(exc.value)


@pytest.mark.parametrize('values', [
    {'smtp_username': 'user'}, {'frontend_confirmation_url': 'https://user:pass@example.com/confirm'},
    {'frontend_confirmation_url': 'https://example.com/confirm?token=secret'},
    {'frontend_confirmation_url': 'https://example.com/confirm#token=secret'},
    {'smtp_backend': 'ses'},
    {'smtp_backend': 'ses', 'smtp_security': 'starttls', 'smtp_username': 'user', 'smtp_password': 'pass'},
    {'smtp_backend': 'ses', 'smtp_security': 'starttls', 'smtp_username': '', 'smtp_password': 'pass', 'frontend_confirmation_url': 'https://example.com/confirm'},
    {'smtp_timeout': 0}, {'smtp_port': 0},
])
def test_invalid_smtp_configuration(values):
    with pytest.raises(ValidationError):
        SmtpSettings(_env_file=None, **values)


def test_valid_ses_configuration_hides_credentials():
    settings = SmtpSettings(_env_file=None, smtp_backend='ses', smtp_host='email-smtp.eu-central-1.amazonaws.com', smtp_port=587, smtp_security='starttls', smtp_username='ses-user', smtp_password='ses-secret', frontend_confirmation_url='https://app.example.com/confirm', frontend_password_reset_url='https://app.example.com/reset-password')
    assert 'ses-secret' not in repr(settings)
    assert settings.smtp_backend == 'ses'


@pytest.mark.parametrize('values', [
    {'outbox_lease_seconds': 30}, {'outbox_retry_base': 50, 'outbox_retry_cap': 5},
    {'outbox_max_attempts': 0}, {'outbox_concurrency': 0},
])
def test_worker_rejects_invalid_configuration(values):
    with pytest.raises(ValidationError):
        OutboxWorkerSettings(_env_file=None, **values)
