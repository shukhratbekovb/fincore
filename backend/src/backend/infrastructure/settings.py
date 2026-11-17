from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_url: SecretStr
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    database_pool_timeout: float = Field(default=30, gt=0)
    health_check_timeout: float = Field(default=2, gt=0, le=10, allow_inf_nan=False)
    log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = 'INFO'
    api_workers: int = Field(default=1, ge=1, le=32)
    redis_url: SecretStr = SecretStr('redis://127.0.0.1:56379/0')
    redis_connect_timeout: float = Field(default=1, gt=0, allow_inf_nan=False)
    redis_socket_timeout: float = Field(default=1, gt=0, allow_inf_nan=False)
    redis_max_connections: int = Field(default=20, ge=1)
    login_rate_limit_ip_per_minute: int = Field(default=30, ge=1, le=2 ** 53 - 1)
    login_rate_limit_username_per_minute: int = Field(default=10, ge=1, le=2 ** 53 - 1)
    register_rate_limit_ip_per_hour: int = Field(default=10, ge=1, le=2 ** 53 - 1)
    register_rate_limit_email_per_hour: int = Field(default=3, ge=1, le=2 ** 53 - 1)
    resend_confirmation_rate_limit_ip_per_hour: int = Field(default=20, ge=1, le=2 ** 53 - 1)
    resend_confirmation_rate_limit_email_per_hour: int = Field(default=3, ge=1, le=2 ** 53 - 1)
    transfer_rate_limit_user_per_minute: int = Field(default=30, ge=1, le=2 ** 53 - 1)
    transfer_rate_limit_ip_per_minute: int = Field(default=100, ge=1, le=2 ** 53 - 1)
    recipient_lookup_rate_limit_user_per_minute: int = Field(default=30, ge=1, le=2 ** 53 - 1)
    recipient_lookup_rate_limit_ip_per_minute: int = Field(default=100, ge=1, le=2 ** 53 - 1)
    jwt_secret_key: SecretStr | None = None
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_access_token_ttl_minutes: int = Field(default=30, ge=1)
    jwt_issuer: str = Field(default="fincore", min_length=1)
    jwt_audience: str = Field(default="fincore-api", min_length=1)
    pagination_secret_key: SecretStr | None = None
    sandbox_enabled: bool = False
    transfer_max_amount_minor: int = Field(default=2 ** 63 - 1, ge=1, le=2 ** 63 - 1)
    sandbox_max_amount_minor: int = Field(default=2 ** 63 - 1, ge=1, le=2 ** 63 - 1)
    verification_confirmation_ttl: timedelta = Field(
        default=timedelta(hours=1),
        gt=timedelta(0),
    )
    session_ttl: timedelta = Field(
        default=timedelta(days=30),
        gt=timedelta(0),
    )
    password_reset_ttl: timedelta = Field(
        default=timedelta(minutes=15),
        gt=timedelta(0),
    )

    @field_validator("jwt_secret_key", "pagination_secret_key")
    @classmethod
    def validate_jwt_secret_key(cls, value: SecretStr | None, info: ValidationInfo) -> SecretStr | None:
        if value is not None:
            secret = value.get_secret_value()
            if not secret.strip() or len(secret.encode("utf-8")) < 32:
                raise ValueError(f"{info.field_name.upper()} must contain at least 32 bytes")
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
        except ArgumentError:
            raise ValueError("DATABASE_URL must be a valid SQLAlchemy URL") from None
        if url.drivername != "postgresql+asyncpg" or not url.database:
            raise ValueError("DATABASE_URL must use postgresql+asyncpg and specify a database")
        return value

    @field_validator('redis_url')
    @classmethod
    def validate_redis_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = urlsplit(value.get_secret_value())
            valid = (
                url.scheme in {'redis', 'rediss'} and bool(url.hostname)
                and (url.port is None or 0 < url.port <= 65535)
                and not url.query and not url.fragment
                and (url.path in {'', '/'} or (url.path.startswith('/') and url.path[1:].isascii() and url.path[1:].isdigit()))
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError('REDIS_URL must be a redis:// or rediss:// URL with an optional database number and no query or fragment') from None
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
