from collections.abc import Callable, Mapping
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.share.errors import UnsupportedOutboxMessageError
from backend.application.share.interfaces.outbox import IOutbox
from backend.application.share.messages import OutboxMessage
from backend.application.notifications.messages import SendPasswordChangedNotification
from backend.application.verification.messages import SendRegistrationConfirmation, SendPasswordResetConfirmation
from backend.domain.user.value_objects import Email
from backend.infrastructure.db.sqlalchemy.models import SqlAlchemyOutboxModel
from backend.infrastructure.db.sqlalchemy.repository.base import SqlAlchemyBaseRepository

MessageSerializer = tuple[str, Callable[[OutboxMessage], dict]]
MessageDeserializer = Callable[[SqlAlchemyOutboxModel], OutboxMessage]


def _registration_payload(message: OutboxMessage) -> dict:
    registration = cast(SendRegistrationConfirmation, message)
    return {
        "user_id": str(registration.user_id),
        "email": registration.email.value,
        "token": registration.token,
        "expires_at": registration.expires_at.isoformat()
    }


def _registration_entity(model: SqlAlchemyOutboxModel) -> SendRegistrationConfirmation:
    payload = model.payload
    if not isinstance(payload, dict) or any(
        not isinstance(payload.get(key), str) for key in ("user_id", "email", "token", "expires_at")
    ):
        raise ValueError("Invalid registration message payload")
    if not payload["token"] or len(payload["token"]) > 512 or any(char.isspace() for char in payload["token"]):
        raise ValueError("Invalid registration token")
    return SendRegistrationConfirmation(
        id=model.id,
        user_id=UUID(payload["user_id"]),
        email=Email(payload["email"]),
        token=payload["token"],
        expires_at=datetime.fromisoformat(payload["expires_at"])
    )


def _password_reset_payload(message: OutboxMessage) -> dict:
    reset = cast(SendPasswordResetConfirmation, message)
    return {
        "user_id": str(reset.user_id), "email": reset.email.value,
        "token": reset.token, "expires_at": reset.expires_at.isoformat(),
    }


def _password_reset_entity(model: SqlAlchemyOutboxModel) -> SendPasswordResetConfirmation:
    payload = model.payload
    if not isinstance(payload, dict) or any(
        not isinstance(payload.get(key), str) for key in ("user_id", "email", "token", "expires_at")
    ):
        raise ValueError("Invalid password reset message payload")
    if not payload["token"] or len(payload["token"]) > 512 or any(char.isspace() for char in payload["token"]):
        raise ValueError("Invalid password reset token")
    return SendPasswordResetConfirmation(
        id=model.id, user_id=UUID(payload["user_id"]), email=Email(payload["email"]),
        token=payload["token"], expires_at=datetime.fromisoformat(payload["expires_at"]),
    )


def _password_changed_payload(message: OutboxMessage) -> dict:
    changed = cast(SendPasswordChangedNotification, message)
    return {
        "user_id": str(changed.user_id), "email": changed.email.value,
        "changed_at": changed.changed_at.isoformat(),
    }


def _password_changed_entity(model: SqlAlchemyOutboxModel) -> SendPasswordChangedNotification:
    payload = model.payload
    if not isinstance(payload, dict) or any(
        not isinstance(payload.get(key), str) for key in ("user_id", "email", "changed_at")
    ):
        raise ValueError("Invalid password changed message payload")
    return SendPasswordChangedNotification(
        id=model.id, user_id=UUID(payload["user_id"]), email=Email(payload["email"]),
        changed_at=datetime.fromisoformat(payload["changed_at"]),
    )


DEFAULT_SERIALIZERS: Mapping[type[OutboxMessage], MessageSerializer] = {
    SendRegistrationConfirmation: (
        "auth.send_registration_confirmation.v1",
        _registration_payload
    ),
    SendPasswordResetConfirmation: ("auth.send_password_reset_confirmation.v1", _password_reset_payload),
    SendPasswordChangedNotification: ("auth.send_password_changed_notification.v1", _password_changed_payload),
}

DEFAULT_DESERIALIZERS: Mapping[str, MessageDeserializer] = {
    "auth.send_registration_confirmation.v1": _registration_entity,
    "auth.send_password_reset_confirmation.v1": _password_reset_entity,
    "auth.send_password_changed_notification.v1": _password_changed_entity,
}


def _to_entity(
        model: SqlAlchemyOutboxModel,
        deserializers: Mapping[str, MessageDeserializer] = DEFAULT_DESERIALIZERS
) -> OutboxMessage:
    deserialize = deserializers.get(model.message_type)
    if deserialize is None:
        raise UnsupportedOutboxMessageError(model.message_type)
    return deserialize(model)


def _to_model(
        entity: OutboxMessage,
        serializers: Mapping[type[OutboxMessage], MessageSerializer] = DEFAULT_SERIALIZERS
) -> SqlAlchemyOutboxModel:
    serializer = serializers.get(type(entity))
    if serializer is None:
        raise UnsupportedOutboxMessageError(type(entity).__name__)
    message_type, encode = serializer
    return SqlAlchemyOutboxModel(
        id=entity.id,
        message_type=message_type,
        payload=encode(entity)
    )


class SqlAlchemyOutbox(
    IOutbox,
    SqlAlchemyBaseRepository
):
    def __init__(
            self,
            session: AsyncSession,
            serializers: Mapping[type[OutboxMessage], MessageSerializer] | None = None
    ):
        SqlAlchemyBaseRepository.__init__(self, session)
        self._serializers = DEFAULT_SERIALIZERS if serializers is None else serializers

    async def add(self, message: OutboxMessage) -> None:
        model = _to_model(message, self._serializers)
        self.session.add(model)
        await self.session.flush()
