from datetime import timedelta

from pydantic import Field
from pydantic_settings import BaseSettings

from backend.application.maintenance.dtos import CleanupPolicy
from backend.infrastructure.settings import Settings


class CleanupSettings(BaseSettings):
    model_config = Settings.model_config

    cleanup_session_retention_days: int = Field(default=7, ge=1, le=36500)
    cleanup_challenge_retention_days: int = Field(default=7, ge=1, le=36500)
    cleanup_outbox_retention_days: int = Field(default=30, ge=1, le=36500)
    cleanup_idempotency_retention_days: int = Field(default=7, ge=1, le=36500)
    cleanup_batch_size: int = Field(default=500, ge=1, le=1000)
    cleanup_max_batches: int = Field(default=20, ge=1, le=1000)
    cleanup_interval_seconds: int = Field(default=86400, ge=60, le=2592000)

    def policy(self) -> CleanupPolicy:
        return CleanupPolicy(
            session_retention=timedelta(days=self.cleanup_session_retention_days),
            challenge_retention=timedelta(days=self.cleanup_challenge_retention_days),
            outbox_retention=timedelta(days=self.cleanup_outbox_retention_days),
            idempotency_retention=timedelta(days=self.cleanup_idempotency_retention_days),
        )
