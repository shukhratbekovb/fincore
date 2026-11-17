import asyncio
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from backend.application.notifications.errors import DeliveryExpiredError, PermanentDeliveryError, TransientDeliveryError
from backend.application.outbox.dtos.delivery import OutboxDelivery
from backend.application.outbox.processor import OutboxProcessor
from backend.application.share.messages import OutboxMessage
from backend.application.verification.handlers.send_registration_confirmation import SendRegistrationConfirmationHandler
from backend.application.verification.messages import SendRegistrationConfirmation
from backend.domain.user.value_objects import Email


@pytest.fixture
def context(now):
    message = SendRegistrationConfirmation(user_id=uuid4(), email=Email('alice@example.com'), token='secret&=value', expires_at=now + timedelta(hours=1))
    delivery = OutboxDelivery(message.id, uuid4(), 1, message)
    queue = AsyncMock()
    queue.claim.return_value = [delivery]
    handler = AsyncMock()
    processor = OutboxProcessor(queue, {SendRegistrationConfirmation: handler})
    return SimpleNamespace(message=message, delivery=delivery, queue=queue, handler=handler, processor=processor)


async def test_processor_acknowledges_only_after_handler(context):
    ctx = context
    assert await ctx.processor.run_once() == 1
    ctx.handler.execute.assert_awaited_once_with(ctx.message)
    ctx.queue.finish.assert_awaited_once_with(ctx.delivery, status='sent')
    ctx.queue.retry.assert_not_awaited()


@pytest.mark.parametrize('error,status,code', [
    (DeliveryExpiredError(), 'expired', 'expired'),
    (PermanentDeliveryError(), 'failed', 'permanent_delivery_error'),
])
async def test_terminal_errors_are_not_retried(context, error, status, code):
    context.handler.execute.side_effect = error
    await context.processor.process(context.delivery)
    context.queue.finish.assert_awaited_once_with(context.delivery, status=status, error_code=code)
    context.queue.retry.assert_not_awaited()


@pytest.mark.parametrize('error,code', [
    (TransientDeliveryError(), 'transient_delivery_error'),
    (TimeoutError(), 'transient_delivery_error'),
    (RuntimeError('secret&=value'), 'processing_error'),
])
async def test_retry_preserves_message_and_uses_safe_error_code(context, error, code, caplog):
    context.handler.execute.side_effect = error
    await context.processor.process(context.delivery)
    arguments = context.queue.retry.call_args
    assert arguments.args[0] is context.delivery
    assert arguments.kwargs['error_code'] == code
    assert 2.5 <= arguments.kwargs['delay'].total_seconds() <= 5
    assert 'secret&=value' not in caplog.text


async def test_total_send_timeout_schedules_retry(context):
    async def slow_send(message):
        await asyncio.sleep(1)
    context.handler.execute.side_effect = slow_send
    await replace(context.processor, send_timeout=0.001).process(context.delivery)
    context.queue.retry.assert_awaited_once()


@pytest.mark.parametrize('attempts', [5, 6])
async def test_attempt_limit_terminates_failed_or_crashed_deliveries(context, attempts):
    context.handler.execute.side_effect = TransientDeliveryError()
    await context.processor.process(replace(context.delivery, attempts=attempts))
    assert context.queue.finish.call_args.kwargs['status'] == 'failed'
    context.queue.retry.assert_not_awaited()
    if attempts == 6:
        context.handler.execute.assert_not_awaited()


async def test_unknown_handler_is_terminal(context):
    await replace(context.processor, handlers={}).process(context.delivery)
    assert context.queue.finish.call_args.kwargs['status'] == 'failed'


async def test_ack_failure_leaves_delivery_for_lease_recovery(context, caplog):
    context.queue.finish.side_effect = RuntimeError('secret payload')
    assert await context.processor.run_once() == 1
    assert 'acknowledgement failed' in caplog.text
    assert 'secret payload' not in caplog.text


async def test_registration_handler_encodes_fragment_and_keeps_message_id(context, now):
    sender, renderer = AsyncMock(), Mock()
    handler = SendRegistrationConfirmationHandler(sender, renderer, SimpleNamespace(now=lambda: now), 'https://app.example.com/confirm', 'example.com')
    await handler.execute(context.message)
    arguments = renderer.registration_confirmation.call_args.kwargs
    assert arguments['confirmation_url'] == 'https://app.example.com/confirm#token=secret%26%3Dvalue'
    assert arguments['message_id'] == f'<{context.message.id}@example.com>'
    sender.send.assert_awaited_once_with(renderer.registration_confirmation.return_value)


@pytest.mark.parametrize('reason', ['expired', 'naive', 'wrong_type'])
async def test_registration_handler_rejects_without_sending(context, now, reason):
    sender, renderer = AsyncMock(), Mock()
    handler = SendRegistrationConfirmationHandler(sender, renderer, SimpleNamespace(now=lambda: now), 'https://app.example.com/confirm', 'example.com')
    message = OutboxMessage() if reason == 'wrong_type' else replace(context.message, expires_at=now if reason == 'expired' else now.replace(tzinfo=None))
    with pytest.raises(DeliveryExpiredError if reason == 'expired' else PermanentDeliveryError):
        await handler.execute(message)
    sender.send.assert_not_awaited()
