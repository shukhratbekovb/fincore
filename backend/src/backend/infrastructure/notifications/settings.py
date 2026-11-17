from typing import Literal

from pydantic import EmailStr, Field, HttpUrl, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.infrastructure.settings import Settings


class SmtpSettings(BaseSettings):
    model_config = SettingsConfigDict(**Settings.model_config)

    smtp_backend: Literal["local", "ses"] = "local"
    smtp_host: str = Field(default="127.0.0.1", min_length=1)
    smtp_port: int = Field(default=1025, ge=1, le=65535)
    smtp_security: Literal["none", "starttls", "tls"] = "none"
    smtp_username: SecretStr | None = None
    smtp_password: SecretStr | None = None
    smtp_from_email: EmailStr = "no-reply@example.com"
    smtp_timeout: float = Field(default=10, gt=0)
    frontend_confirmation_url: HttpUrl = "http://localhost:3000/confirm"
    frontend_password_reset_url: HttpUrl = "http://localhost:3000/reset-password"
    email_locale: Literal["ru", "en"] = "ru"

    @model_validator(mode="after")
    def validate_configuration(self) -> "SmtpSettings":
        for url in (self.frontend_confirmation_url, self.frontend_password_reset_url):
            if url.username or url.password or url.query or url.fragment:
                raise ValueError("Frontend URLs must not contain credentials, query or fragment")
        if (self.smtp_username is None) != (self.smtp_password is None):
            raise ValueError("SMTP username and password must be configured together")
        if self.smtp_backend == "ses":
            if self.smtp_security == "none" or not self.smtp_username or not self.smtp_password:
                raise ValueError("SES requires TLS/STARTTLS and SMTP credentials")
            if not self.smtp_username.get_secret_value().strip() or not self.smtp_password.get_secret_value().strip():
                raise ValueError("SES SMTP credentials must not be empty")
            if any(url.scheme != "https" for url in (self.frontend_confirmation_url, self.frontend_password_reset_url)):
                raise ValueError("SES requires HTTPS confirmation and password reset URLs")
        return self


class OutboxWorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(**Settings.model_config)

    outbox_concurrency: int = Field(default=4, ge=1, le=32)
    outbox_poll_interval: float = Field(default=1, gt=0)
    outbox_lease_seconds: float = Field(default=60, gt=0)
    outbox_send_timeout: float = Field(default=30, gt=0)
    outbox_max_attempts: int = Field(default=5, ge=1, le=100)
    outbox_retry_base: float = Field(default=5, gt=0)
    outbox_retry_cap: float = Field(default=300, gt=0)

    @model_validator(mode="after")
    def validate_timeouts(self) -> "OutboxWorkerSettings":
        if self.outbox_lease_seconds <= self.outbox_send_timeout + 5:
            raise ValueError("Outbox lease must exceed total send timeout by more than five seconds")
        if self.outbox_retry_cap < self.outbox_retry_base:
            raise ValueError("Outbox retry cap must be at least retry base")
        return self
