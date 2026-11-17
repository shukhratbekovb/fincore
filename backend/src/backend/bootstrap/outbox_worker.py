import argparse
import asyncio
import logging
import signal
from datetime import timedelta

from backend.application.outbox.processor import OutboxProcessor
from backend.application.notifications.handlers.send_password_changed import SendPasswordChangedNotificationHandler
from backend.application.notifications.messages import SendPasswordChangedNotification
from backend.application.verification.handlers.send_password_reset_confirmation import SendPasswordResetConfirmationHandler
from backend.application.verification.handlers.send_registration_confirmation import SendRegistrationConfirmationHandler
from backend.application.verification.messages import SendRegistrationConfirmation, SendPasswordResetConfirmation
from backend.infrastructure.clock import SystemClock
from backend.infrastructure.db.sqlalchemy.core.database import create_engine, create_session_factory
from backend.infrastructure.db.sqlalchemy.repository.outbox_queue import SqlAlchemyOutboxQueue
from backend.infrastructure.notifications.jinja_renderer import JinjaEmailRenderer
from backend.infrastructure.notifications.settings import OutboxWorkerSettings, SmtpSettings
from backend.infrastructure.notifications.smtp_sender import SmtpEmailSender
from backend.infrastructure.settings import get_settings
from backend.infrastructure.logging import configure_logging

logger = logging.getLogger(__name__)


def build_processor(session_factory, smtp: SmtpSettings, worker: OutboxWorkerSettings) -> OutboxProcessor:
    sender, renderer, clock = SmtpEmailSender(smtp), JinjaEmailRenderer(smtp.email_locale), SystemClock()
    message_id_domain = str(smtp.smtp_from_email).rsplit("@", 1)[1]
    handler = SendRegistrationConfirmationHandler(
        sender=sender, renderer=renderer, clock=clock,
        confirmation_url=str(smtp.frontend_confirmation_url),
        message_id_domain=message_id_domain,
    )
    reset_handler = SendPasswordResetConfirmationHandler(
        sender=sender, renderer=renderer, clock=clock,
        confirmation_url=str(smtp.frontend_password_reset_url), message_id_domain=message_id_domain,
    )
    changed_handler = SendPasswordChangedNotificationHandler(
        sender=sender, renderer=renderer, message_id_domain=message_id_domain,
    )
    return OutboxProcessor(
        queue=SqlAlchemyOutboxQueue(session_factory), handlers={
            SendRegistrationConfirmation: handler,
            SendPasswordResetConfirmation: reset_handler,
            SendPasswordChangedNotification: changed_handler,
        },
        concurrency=worker.outbox_concurrency, lease=timedelta(seconds=worker.outbox_lease_seconds),
        send_timeout=worker.outbox_send_timeout, max_attempts=worker.outbox_max_attempts,
        retry_base=worker.outbox_retry_base, retry_cap=worker.outbox_retry_cap,
    )


async def run_loop(processor: OutboxProcessor, stop: asyncio.Event, poll_interval: float) -> None:
    while not stop.is_set():
        try:
            count = await processor.run_once()
        except Exception:
            logger.error("Outbox polling failed; retrying without logging connection or payload details")
            count = 0
        if not count:
            try:
                await asyncio.wait_for(stop.wait(), timeout=poll_interval)
            except TimeoutError:
                pass


async def run(*, once: bool = False) -> None:
    smtp, worker = SmtpSettings(), OutboxWorkerSettings()
    engine = create_engine(get_settings())
    try:
        processor = build_processor(create_session_factory(engine), smtp, worker)
        if once:
            await processor.run_once()
            return
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, stop.set)
        try:
            await run_loop(processor, stop, worker.outbox_poll_interval)
        finally:
            for signum in (signal.SIGINT, signal.SIGTERM):
                loop.remove_signal_handler(signum)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Deliver outbox emails via local SMTP or Amazon SES SMTP")
    parser.add_argument("--once", action="store_true", help="Process one available batch and exit")
    arguments = parser.parse_args()
    configure_logging(get_settings().log_level)
    asyncio.run(run(once=arguments.once))


if __name__ == "__main__":
    main()
