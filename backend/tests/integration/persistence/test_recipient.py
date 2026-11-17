from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event

from backend.application.wallet.dtos.resolve_recipient import ResolveWalletRecipientCommand
from backend.application.wallet.errors import WalletNotFoundError
from backend.application.wallet.queries.resolve_recipient import ResolveWalletRecipientQuery
from backend.domain.user.entities import User
from backend.domain.user.value_objects import Username, Email, HashedPassword
from backend.domain.wallet.entities import Wallet
from backend.domain.wallet.value_objects import WalletName, WalletNumber
from backend.domain.share.enums import CurrencyEnum
from backend.infrastructure.db.sqlalchemy.core.uow import SqlAlchemyUnitOfWork


@pytest.fixture
async def ctx(session_factory):
    sender = User.created_by_admin(Username('sender'), Email('sender@example.com'), HashedPassword('unused'))
    receiver = User.created_by_admin(Username('receiver'), Email('receiver@example.com'), HashedPassword('unused'))
    wallet = Wallet.create(receiver.id, WalletName('Private name'), WalletNumber('00001234567890123456'), CurrencyEnum.CAD)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.users.add(sender)
        await uow.users.add(receiver)
        await uow.wallets.add(wallet)
        await uow.commit()
    return SimpleNamespace(factory=session_factory, sender=sender, receiver=receiver, wallet=wallet)


async def test_indexed_exact_lookup_joins_receiver_username_in_one_select(ctx):
    statements = []
    engine = ctx.factory.kw['bind'].sync_engine
    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        async with SqlAlchemyUnitOfWork(ctx.factory) as uow:
            recipient = await uow.wallet_reader.get_recipient_by_number(ctx.wallet.number)
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert recipient.wallet_id == ctx.wallet.id and recipient.number == ctx.wallet.number.value
    assert recipient.owner == 'receiver' and recipient.currency == CurrencyEnum.CAD
    assert len(statements) == 1 and 'JOIN users' in statements[0] and 'FOR UPDATE' not in statements[0]
    assert 'wallets.number =' in statements[0]


@pytest.mark.parametrize('state', ['missing', 'frozen', 'closed', 'suspended_owner', 'pending_owner', 'closed_owner'])
async def test_unavailable_wallets_and_inactive_owners_have_same_not_found(ctx, state):
    async with SqlAlchemyUnitOfWork(ctx.factory) as uow:
        if state in {'frozen', 'closed'}:
            wallet = await uow.wallets.get_by_id_for_update(ctx.wallet.id)
            wallet.freeze() if state == 'frozen' else wallet.close()
            await uow.wallets.save(wallet)
        elif state.endswith('_owner'):
            from backend.domain.user.enums import UserStatusEnum
            owner = await uow.users.get_by_id_for_update(ctx.receiver.id)
            owner.status = {'suspended_owner': UserStatusEnum.SUSPENDED, 'pending_owner': UserStatusEnum.PENDING_CONFIRMATION,
                            'closed_owner': UserStatusEnum.CLOSED}[state]
            await uow.users.save(owner)
        await uow.commit()
    number = WalletNumber('9' * 20) if state == 'missing' else ctx.wallet.number
    with pytest.raises(WalletNotFoundError):
        await ResolveWalletRecipientQuery(SqlAlchemyUnitOfWork(ctx.factory)).execute(ResolveWalletRecipientCommand(ctx.sender.id, number))


async def test_own_wallet_is_also_resolvable(ctx):
    result = await ResolveWalletRecipientQuery(SqlAlchemyUnitOfWork(ctx.factory)).execute(ResolveWalletRecipientCommand(ctx.receiver.id, ctx.wallet.number))
    assert result.owner == 'receiver'
