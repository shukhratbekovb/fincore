from typing import Protocol

from backend.domain.sandbox_top_up.entities import SandboxTopUp


class ISandboxTopUpRepository(Protocol):
    async def add(self, top_up: SandboxTopUp) -> None:
        """Persist in the caller's UoW; never commit independently.

        Do not commit PENDING. A successful top-up must be committed with
        exactly one balanced journal, its projection and its replay result.
        """
        ...
