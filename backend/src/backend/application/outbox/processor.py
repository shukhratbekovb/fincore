import asyncio
import logging
import random
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta

from backend.application.notifications.errors import (
    DeliveryExpiredError, PermanentDeliveryError, TransientDeliveryError,
)
from backend.application.outbox.dtos.delivery import OutboxDelivery
from backend.application.outbox.interfaces.handler import IOutboxHandler
from backend.application.outbox.interfaces.queue import IOutboxQueue
from backend.application.share.messages import OutboxMessage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutboxProcessor:
    queue: IOutboxQueue
    handlers: Mapping[type[OutboxMessage], IOutboxHandler]
    concurrency: int = 4
    lease: timedelta = timedelta(seconds=60)
    send_timeout: float = 30
    max_attempts: int = 5
    retry_base: float = 5
    retry_cap: float = 300

    async def run_once(self) -> int:
        deliveries = await self.queue.claim(limit=self.concurrency, lease=self.lease)
        results = await asyncio.gather(*(self.process(delivery) for delivery in deliveries), return_exceptions=True)
        for delivery, result in zip(deliveries, results):
            if isinstance(result, BaseException):
                logger.error("Outbox acknowledgement failed; lease will recover: id=%s", delivery.id)
        return len(deliveries)

    async def process(self, delivery: OutboxDelivery) -> None:
        if delivery.attempts > self.max_attempts:
            await self.queue.finish(delivery, status="failed", error_code="attempts_exhausted")
            return
        handler = self.handlers.get(type(delivery.message))
        try:
            if handler is None:
                raise PermanentDeliveryError()
            async with asyncio.timeout(self.send_timeout):
                await handler.execute(delivery.message)
        except DeliveryExpiredError:
            await self.queue.finish(delivery, status="expired", error_code="expired")
        except PermanentDeliveryError:
            await self.queue.finish(delivery, status="failed", error_code="permanent_delivery_error")
        except (TransientDeliveryError, TimeoutError):
            await self._retry(delivery, "transient_delivery_error")
        except Exception:
            # Never persist/log arbitrary exception text, recipient or secret payload.
            await self._retry(delivery, "processing_error")
        else:
            await self.queue.finish(delivery, status="sent")

    async def _retry(self, delivery: OutboxDelivery, error_code: str) -> None:
        logger.warning("Outbox attempt failed: id=%s attempt=%s code=%s", delivery.id, delivery.attempts, error_code)
        if delivery.attempts >= self.max_attempts:
            await self.queue.finish(delivery, status="failed", error_code=error_code)
            return
        maximum = min(self.retry_cap, self.retry_base * 2 ** min(delivery.attempts - 1, 20))
        delay = timedelta(seconds=random.uniform(maximum / 2, maximum))
        await self.queue.retry(delivery, delay=delay, error_code=error_code)
