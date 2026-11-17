from dataclasses import dataclass, fields
from datetime import timedelta

from backend.application.maintenance.dtos import CleanupExpiredDataCommand, CleanupPolicy, CleanupReport
from backend.application.maintenance.interfaces.store import IMaintenanceStore


@dataclass(frozen=True)
class CleanupExpiredDataUseCase:
    store: IMaintenanceStore

    async def execute(self, cmd: CleanupExpiredDataCommand) -> CleanupReport:
        if not isinstance(cmd.policy, CleanupPolicy):
            raise TypeError("Cleanup policy is required")
        for field in fields(cmd.policy):
            value = getattr(cmd.policy, field.name)
            if not isinstance(value, timedelta) or not timedelta(days=1) <= value <= timedelta(days=36500):
                raise ValueError("Retention must be between 1 and 36500 days")
        if type(cmd.batch_size) is not int or not 1 <= cmd.batch_size <= 1000:
            raise ValueError("Batch size must be an integer between 1 and 1000")
        if type(cmd.max_batches) is not int or not 1 <= cmd.max_batches <= 1000:
            raise ValueError("Max batches must be an integer between 1 and 1000")
        if type(cmd.dry_run) is not bool:
            raise TypeError("Dry run must be a boolean")
        return await self.store.cleanup(cmd)
