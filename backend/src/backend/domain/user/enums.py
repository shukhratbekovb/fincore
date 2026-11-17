from enum import Enum


class UserStatusEnum(str, Enum):
    ACTIVE = 'active'
    PENDING_CONFIRMATION = 'pending_confirmation'
    SUSPENDED = 'suspended'
    CLOSED = 'closed'