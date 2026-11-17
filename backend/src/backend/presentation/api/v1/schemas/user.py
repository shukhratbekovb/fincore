from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UserResponse(BaseModel):
    id: UUID
    username: str
    email: str
    created_at: datetime


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    expires_at: datetime
    ip_address: str
    created_at: datetime
    user_agent: str | None = None
    last_ip_address: str | None = None
    last_user_agent: str | None = None
    last_used_at: datetime | None = None
