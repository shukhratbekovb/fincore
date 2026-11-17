from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class CleanupPolicy:
    session_retention: timedelta = timedelta(days=7)
    challenge_retention: timedelta = timedelta(days=7)
    outbox_retention: timedelta = timedelta(days=30)
    idempotency_retention: timedelta = timedelta(days=7)


@dataclass(frozen=True)
class CleanupExpiredDataCommand:
    policy: CleanupPolicy = CleanupPolicy()
    batch_size: int = 500
    max_batches: int = 20
    dry_run: bool = False


@dataclass(frozen=True, kw_only=True)
class CleanupReport:
    as_of: datetime
    dry_run: bool
    sessions: int = 0
    refresh_tokens: int = 0
    verification_challenges: int = 0
    outbox_messages: int = 0
    idempotency_records: int = 0
    receipts_created: int = 0
    batch_limit_reached: bool = False
