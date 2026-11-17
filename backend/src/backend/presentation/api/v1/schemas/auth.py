from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

UsernameValue = Annotated[str, Field(
    min_length=5,
    max_length=256,
    pattern=r"^[a-zA-Z][a-zA-Z0-9_]*[a-zA-Z0-9]$",
)]
TokenValue = Annotated[str, Field(min_length=1, max_length=512, pattern=r"^\S+$", repr=False)]


class TokenResponse(BaseModel):
    access_token: str = Field(repr=False)
    refresh_token: str = Field(repr=False)


class LoginUserSchema(BaseModel):
    username: UsernameValue
    password: str = Field(min_length=1, max_length=256, repr=False, json_schema_extra={"format": "password"})


class RegisterUserSchema(BaseModel):
    username: UsernameValue
    email: EmailStr = Field(max_length=512)


class RegisterUserResponse(BaseModel):
    user_id: UUID


class ResendRegistrationConfirmationSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr = Field(max_length=512)


class RegistrationConfirmationRequestedResponse(BaseModel):
    message: str


class RefreshSessionSchema(BaseModel):
    refresh_token: TokenValue


class LogoutUserSchema(RefreshSessionSchema):
    pass


class ConfirmUserSchema(BaseModel):
    token: TokenValue
    password: str = Field(min_length=8, max_length=256, repr=False, json_schema_extra={"format": "password"})


class ChangePasswordSchema(BaseModel):
    current_password: str = Field(min_length=8, max_length=256, repr=False, json_schema_extra={"format": "password"})
    new_password: str = Field(min_length=8, max_length=256, repr=False, json_schema_extra={"format": "password"})


class RequestPasswordResetSchema(BaseModel):
    email: EmailStr = Field(max_length=512)


class ConfirmPasswordResetSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: TokenValue


class PasswordResetRequestedResponse(BaseModel):
    message: str


class PasswordResetResponse(BaseModel):
    password: str = Field(repr=False, json_schema_extra={"format": "password", "readOnly": True})
