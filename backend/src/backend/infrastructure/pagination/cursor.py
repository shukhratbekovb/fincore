import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from backend.application.share.dtos.pagination import CursorPosition
from backend.application.share.errors import InvalidCursorError
from backend.application.share.interfaces.cursor_codec import ICursorCodec


@dataclass(frozen=True)
class HMACCursorCodec(ICursorCodec):
    key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.key, bytes) or len(self.key) < 32:
            raise ValueError("Cursor signing key must contain at least 32 bytes")

    def encode(self, position: CursorPosition, *, context: str) -> str:
        payload = json.dumps(
            {
                "v": 1,
                "ctx": hashlib.sha256(context.encode("utf-8")).hexdigest(),
                "timestamp": position.timestamp.astimezone(timezone.utc).isoformat(),
                "id": str(position.id),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        signature = hmac.digest(self.key, payload, "sha256")
        return f"{self._encode_part(payload)}.{self._encode_part(signature)}"

    def decode(self, cursor: str, *, context: str) -> CursorPosition:
        try:
            if not isinstance(cursor, str) or not 1 <= len(cursor) <= 2048:
                raise InvalidCursorError()
            payload_part, signature_part = cursor.split(".")
            payload = self._decode_part(payload_part)
            signature = self._decode_part(signature_part)
            if not hmac.compare_digest(hmac.digest(self.key, payload, "sha256"), signature):
                raise InvalidCursorError()
            data = json.loads(payload)
            if (
                not isinstance(data, dict)
                or set(data) != {"v", "ctx", "timestamp", "id"}
                or type(data["v"]) is not int
                or data["v"] != 1
                or data["ctx"] != hashlib.sha256(context.encode("utf-8")).hexdigest()
            ):
                raise InvalidCursorError()
            return CursorPosition(timestamp=datetime.fromisoformat(data["timestamp"]), id=UUID(data["id"]))
        except (ValueError, TypeError, AttributeError, UnicodeError, binascii.Error) as exc:
            raise InvalidCursorError() from exc

    @staticmethod
    def _encode_part(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    @staticmethod
    def _decode_part(value: str) -> bytes:
        return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
