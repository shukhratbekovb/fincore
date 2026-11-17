from typing import Protocol

from backend.application.maintenance.dtos import CleanupExpiredDataCommand, CleanupReport


class IMaintenanceStore(Protocol):
    async def cleanup(self, cmd: CleanupExpiredDataCommand) -> CleanupReport:
        """Use database time and short transactions; preserve financial replay and records."""
        ...
