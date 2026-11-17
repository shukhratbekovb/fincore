from datetime import datetime, timezone

from backend.application.share.interfaces.clock import IClock


class SystemClock(IClock):
    def now(self) -> datetime:
        return datetime.now(tz=timezone.utc)