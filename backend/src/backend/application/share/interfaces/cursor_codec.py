from typing import Protocol

from backend.application.share.dtos.pagination import CursorPosition


class ICursorCodec(Protocol):
    def encode(self, position: CursorPosition, *, context: str) -> str: ...

    def decode(self, cursor: str, *, context: str) -> CursorPosition:
        """Verify integrity and request context, or raise InvalidCursorError.

        Context binds the cursor to actor, query and normalized filters. Cursor
        contents never grant access; readers must always apply the actor scope.
        """
        ...
