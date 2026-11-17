import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.application.notifications.errors import DeliveryExpiredError, PermanentDeliveryError
from backend.application.notifications.handlers.send_password_changed import SendPasswordChangedNotificationHandler
from backend.application.notifications.messages import SendPasswordChangedNotification
from backend.application.verification.handlers.send_password_reset_confirmation import SendPasswordResetConfirmationHandler
from backend.application.verification.messages import SendPasswordResetConfirmation
from backend.domain.user.value_objects import Email, RawPassword
from backend.infrastructure.db.sqlalchemy.repository.outbox import _to_entity, _to_model
from backend.infrastructure.notifications.jinja_renderer import JinjaEmailRenderer
from backend.infrastructure.notifications.settings import SmtpSettings
from backend.infrastructure.security import password_generator
from backend.infrastructure.settings import Settings


def test_password_generator_has_no_import_side_effects_and_always_meets_policy(capsys):
    importlib.reload(password_generator)
    assert capsys.readouterr().out == ''
    passwords = {password_generator.PasswordGenerator().generate().value for _ in range(100)}
    assert len(passwords) == 100
    assert all(RawPassword(password).value == password for password in passwords)


@pytest.mark.parametrize('kind', ['reset', 'changed'])
async def test_outbox_roundtrip_handler_and_bilingual_templates(now, kind):
    for locale in ('ru', 'en'):
        sender = SimpleNamespace(send=AsyncMock())
        if kind == 'reset':
            message = SendPasswordResetConfirmation(user_id=uuid4(), email=Email('alice@example.com'), token='<secret>&', expires_at=now)
            handler = SendPasswordResetConfirmationHandler(sender, JinjaEmailRenderer(locale),
                SimpleNamespace(now=lambda: now.replace(year=now.year - 1)), 'https://app.example.com/reset', 'example.com')
        else:
            message = SendPasswordChangedNotification(user_id=uuid4(), email=Email('alice@example.com'), changed_at=now)
            handler = SendPasswordChangedNotificationHandler(sender, JinjaEmailRenderer(locale), 'example.com')
        model = _to_model(message)
        assert _to_entity(model) == message
        await handler.execute(_to_entity(model))
        email = sender.send.call_args.args[0]
        assert email.message_id == f'<{message.id}@example.com>'
        assert email.subject and 'FinCore' in email.subject
        assert email.html and email.text and 'UTC' in email.text
        if kind == 'reset':
            assert '#token=%3Csecret%3E%26' in email.text
            assert '<secret>' not in email.html
        else:
            assert set(model.payload) == {'user_id', 'email', 'changed_at'}
            assert 'token=' not in email.html


@pytest.mark.parametrize('kind,problem', [
    ('reset', 'wrong_type'), ('reset', 'naive'), ('reset', 'expired'),
    ('changed', 'wrong_type'), ('changed', 'naive'),
])
async def test_handlers_reject_wrong_types_dates_and_expiry_before_sending(now, kind, problem):
    sender = SimpleNamespace(send=AsyncMock())
    message = (SendPasswordResetConfirmation(user_id=uuid4(), email=Email('alice@example.com'), token='secret',
               expires_at=now.replace(tzinfo=None) if problem == 'naive' else now) if kind == 'reset'
               else SendPasswordChangedNotification(user_id=uuid4(), email=Email('alice@example.com'),
               changed_at=now.replace(tzinfo=None) if problem == 'naive' else now))
    handler = (SendPasswordResetConfirmationHandler(sender, JinjaEmailRenderer(), SimpleNamespace(now=lambda: now),
               'https://app.example.com/reset', 'example.com') if kind == 'reset'
               else SendPasswordChangedNotificationHandler(sender, JinjaEmailRenderer(), 'example.com'))
    error = DeliveryExpiredError if problem == 'expired' else PermanentDeliveryError
    with pytest.raises(error):
        await handler.execute(object() if problem == 'wrong_type' else message)
    sender.send.assert_not_awaited()


@pytest.mark.parametrize('kind,corruption', [('reset', 'shape'), ('reset', 'token'), ('changed', 'shape')])
def test_corrupted_payload_is_rejected(now, kind, corruption):
    message = (SendPasswordResetConfirmation(user_id=uuid4(), email=Email('alice@example.com'), token='secret', expires_at=now)
               if kind == 'reset' else SendPasswordChangedNotification(user_id=uuid4(), email=Email('alice@example.com'), changed_at=now))
    model = _to_model(message)
    model.payload = {} if corruption == 'shape' else {**model.payload, 'token': 'has whitespace'}
    with pytest.raises(ValueError):
        _to_entity(model)


@pytest.mark.parametrize('url', ['https://user:pass@example.com/reset', 'https://app.example.com/reset?token=secret', 'https://app.example.com/reset#token=secret'])
def test_reset_frontend_url_cannot_embed_credentials_or_token(url):
    with pytest.raises(ValidationError):
        SmtpSettings(_env_file=None, frontend_password_reset_url=url)


def test_reset_ttl_is_configurable_and_positive():
    settings = Settings(_env_file=None, database_url='postgresql+asyncpg://localhost/fincore_test', password_reset_ttl='PT10M')
    assert settings.password_reset_ttl.total_seconds() == 600
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url='postgresql+asyncpg://localhost/fincore_test', password_reset_ttl=0)
