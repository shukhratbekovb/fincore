from typing import Protocol
from uuid import UUID


class ISandboxOperatorReader(Protocol):
    async def is_operator(self, user_id: UUID) -> bool:
        """Read current server-managed permission in the active UoW.

        Never trust a request flag or infer permission from wallet ownership.
        Grant/revoke operations must lock the same user row before changing
        permission, so the use case's locked recheck remains valid until commit.
        """
        ...
