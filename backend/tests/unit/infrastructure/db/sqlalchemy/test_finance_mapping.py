from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from backend.domain.share.enums import CurrencyEnum
from backend.domain.transfer.entities import Transfer
from backend.domain.sandbox_top_up.entities import SandboxTopUp
from backend.domain.ledger_account.entities import LedgerAccount
from backend.domain.ledger_transaction.entities import LedgerTransaction
from backend.domain.transfer.enums import TransferRejectionCodeEnum
from backend.domain.sandbox_top_up.enums import SandboxTopUpRejectionCodeEnum
from backend.infrastructure.db.sqlalchemy.repository import transfer as transfer_mapping, sandbox_top_up as top_up_mapping, ledger_transaction as journal_mapping
from backend.infrastructure.db.sqlalchemy.models import SqlAlchemyLedgerEntryModel
from backend.infrastructure.settings import Settings
from backend.presentation.api.v1.dependencies.finance import get_cursor_codec
from backend.presentation.api.v1.schemas.finance import CreateTransferSchema, CreateSandboxTopUpSchema


@pytest.mark.parametrize('completed', [True, False])
def test_transfer_and_top_up_mapping_preserves_domain_state(now, completed):
    transfer = Transfer.create(sender_wallet_id=uuid4(), receiver_wallet_id=uuid4(), amount_minor=100, currency=CurrencyEnum.USD, now=now)
    top_up = SandboxTopUp.create(wallet_id=transfer.sender_wallet_id, initiated_by_user_id=uuid4(), amount_minor=100, currency=CurrencyEnum.USD, now=now)
    if completed:
        transfer.complete(now=now)
        top_up.complete(now=now)
    else:
        transfer.reject(TransferRejectionCodeEnum.INSUFFICIENT_FUNDS, now=now)
        top_up.reject(SandboxTopUpRejectionCodeEnum.LIMIT_EXCEEDED, now=now)
    assert transfer_mapping._to_entity(transfer_mapping._to_model(transfer)) == transfer
    assert top_up_mapping._to_entity(top_up_mapping._to_model(top_up)) == top_up


def test_whole_journal_mapping_restores_entries(now):
    transfer = Transfer.create(sender_wallet_id=uuid4(), receiver_wallet_id=uuid4(), amount_minor=100, currency=CurrencyEnum.USD, now=now)
    transfer.complete(now=now)
    journal = LedgerTransaction.for_transfer(
        transfer=transfer,
        sender_account=LedgerAccount.for_wallet(wallet_id=transfer.sender_wallet_id, currency=CurrencyEnum.USD, now=now),
        receiver_account=LedgerAccount.for_wallet(wallet_id=transfer.receiver_wallet_id, currency=CurrencyEnum.USD, now=now), now=now,
    )
    entries = [SqlAlchemyLedgerEntryModel(
        id=e.id, ledger_transaction_id=e.ledger_transaction_id, ledger_account_id=e.ledger_account_id,
        side=e.side.value, amount_minor=e.amount_minor, currency=e.currency.value, created_at=e.created_at,
    ) for e in journal.entries]
    assert journal_mapping._to_entity(journal_mapping._to_model(journal), entries) == journal


@pytest.mark.parametrize('amount', [True, 1.5, '1.5', '-1', '', '１２', None])
@pytest.mark.parametrize('model', [CreateTransferSchema, CreateSandboxTopUpSchema])
def test_http_amount_rejects_coercions_and_non_integer_strings(amount, model):
    data = {'amount_minor': amount, 'currency': 'USD'}
    if model is CreateTransferSchema:
        data.update(sender_wallet_id=uuid4(), receiver_wallet_id=uuid4())
    else:
        data['wallet_id'] = uuid4()
    with pytest.raises(ValidationError):
        model.model_validate(data)


def test_request_cannot_supply_actor_or_operator_permission():
    with pytest.raises(ValidationError):
        CreateSandboxTopUpSchema(wallet_id=uuid4(), amount_minor='1', currency='USD', user_id=uuid4(), is_operator=True)


def test_cursor_dependency_supports_independent_key_or_domain_separated_jwt_key():
    settings = Settings(_env_file=None, database_url='postgresql+asyncpg://localhost/test', jwt_secret_key='test-key-only-' * 4)
    first = get_cursor_codec(settings)
    assert len(first.key) == 32
    assert first.key != settings.jwt_secret_key.get_secret_value().encode()
    settings.pagination_secret_key = SecretStr('separate-test-key-only-' * 2)
    assert get_cursor_codec(settings).key == settings.pagination_secret_key.get_secret_value().encode()
    settings.pagination_secret_key = None
    settings.jwt_secret_key = None
    with pytest.raises(RuntimeError):
        get_cursor_codec(settings)
