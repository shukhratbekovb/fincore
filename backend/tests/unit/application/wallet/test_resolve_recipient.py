from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from backend.application.auth.errors import UserInactiveError
from backend.application.user.errors import UserNotFoundError
from backend.application.wallet.dtos.resolve_recipient import ResolveWalletRecipientCommand, WalletRecipientDTO
from backend.application.wallet.errors import WalletNotFoundError
from backend.application.wallet.queries.resolve_recipient import ResolveWalletRecipientQuery
from backend.domain.share.enums import CurrencyEnum
from backend.domain.wallet.value_objects import WalletNumber


@pytest.fixture
def ctx():
    user = SimpleNamespace(id=uuid4(), is_active=lambda: True)
    recipient = WalletRecipientDTO(uuid4(), '00001234567890123456', CurrencyEnum.CAD, 'receiver_user')
    uow = AsyncMock()
    uow.users.get_by_id.return_value = user
    uow.wallet_reader.get_recipient_by_number.return_value = recipient
    return SimpleNamespace(user=user, recipient=recipient, uow=uow,
                           query=ResolveWalletRecipientQuery(uow),
                           cmd=ResolveWalletRecipientCommand(user.id, WalletNumber(recipient.number)))


async def test_resolves_exact_number_read_only_and_returns_recipient_username(ctx):
    assert await ctx.query.execute(ctx.cmd) is ctx.recipient
    ctx.uow.users.get_by_id.assert_awaited_once_with(ctx.user.id)
    ctx.uow.wallet_reader.get_recipient_by_number.assert_awaited_once_with(ctx.cmd.wallet_number)
    ctx.uow.commit.assert_not_awaited()
    ctx.uow.wallets.get_by_id_for_update.assert_not_awaited()


@pytest.mark.parametrize('missing', [True, False])
async def test_actor_is_checked_before_recipient_lookup(ctx, missing):
    ctx.uow.users.get_by_id.return_value = None if missing else SimpleNamespace(is_active=lambda: False)
    with pytest.raises(UserNotFoundError if missing else UserInactiveError):
        await ctx.query.execute(ctx.cmd)
    ctx.uow.wallet_reader.get_recipient_by_number.assert_not_awaited()


async def test_unavailable_recipient_has_the_standard_not_found_error(ctx):
    ctx.uow.wallet_reader.get_recipient_by_number.return_value = None
    with pytest.raises(WalletNotFoundError):
        await ctx.query.execute(ctx.cmd)
