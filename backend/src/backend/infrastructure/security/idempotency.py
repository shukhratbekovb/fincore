import hashlib
import json
from uuid import UUID


def idempotency_key_digest(*, user_id: UUID, scope: str, key: str) -> str:
    """Permanent receipt identity without retaining a raw client key or actor ID."""
    identity = json.dumps([str(user_id), scope, key], separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(identity.encode("ascii")).hexdigest()
