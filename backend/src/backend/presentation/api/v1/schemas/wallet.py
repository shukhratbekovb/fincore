from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from backend.domain.share.enums import CurrencyEnum
from backend.domain.wallet.enums import WalletStatusEnum
from backend.domain.wallet.value_objects import WALLET_NAME_MAX_LENGTH
from backend.presentation.api.v1.schemas.finance import MoneyAmount


WalletNameValue = Annotated[str, StringConstraints(
    strip_whitespace=True,
    min_length=1,
    max_length=WALLET_NAME_MAX_LENGTH,
)]


class RenameWalletSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: WalletNameValue


class CreateWalletSchema(RenameWalletSchema):
    currency: CurrencyEnum = CurrencyEnum.USD


class CreateWalletResponse(BaseModel):
    wallet_id: UUID


class ResolveWalletRecipientSchema(BaseModel):
    model_config = ConfigDict(extra='forbid')
    wallet_number: Annotated[str, StringConstraints(min_length=20, max_length=20, pattern=r'^[0-9]{20}$')]


class WalletRecipientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    wallet_id: UUID
    number: str = Field(pattern=r'^[0-9]{20}$')
    currency: CurrencyEnum
    owner: str = Field(description='Username of the owner of the recipient wallet.')


class WalletResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    name: str
    balance_minor: MoneyAmount
    number: str = Field(pattern=r"^[0-9]{20}$")
    currency: CurrencyEnum
    status: WalletStatusEnum
    created_at: datetime
    updated_at: datetime
