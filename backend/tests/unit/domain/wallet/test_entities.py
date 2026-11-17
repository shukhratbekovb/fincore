from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.domain.share.enums import CurrencyEnum
from backend.domain.wallet.entities import Wallet
from backend.domain.wallet.enums import WalletStatusEnum
from backend.domain.wallet.errors import WalletClosedError, WalletNotActiveError, WalletNotFrozenError
from backend.domain.wallet.value_objects import WalletName, WalletNumber


@pytest.fixture
def wallet():
    return Wallet.create(user_id=uuid4(), name=WalletName('Main'),
                         number=WalletNumber('12345678901234567890'), currency=CurrencyEnum.EUR)


def test_create_preserves_owner_name_number_currency(wallet):
    assert wallet.user_id is not None
    assert wallet.name == WalletName('Main')
    assert wallet.number == WalletNumber('12345678901234567890')
    assert wallet.currency == CurrencyEnum.EUR
    assert wallet.status == WalletStatusEnum.ACTIVE


def test_freeze_and_unfreeze(wallet):
    wallet.updated_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
    wallet.freeze()
    assert wallet.status == WalletStatusEnum.FROZEN
    assert wallet.updated_at.year > 2000
    wallet.updated_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
    wallet.unfreeze()
    assert wallet.status == WalletStatusEnum.ACTIVE
    assert wallet.updated_at.year > 2000


@pytest.mark.parametrize('frozen', [False, True])
def test_close_is_terminal_and_idempotent(wallet, frozen):
    if frozen:
        wallet.freeze()
    wallet.close()
    assert wallet.status == WalletStatusEnum.CLOSED
    before = vars(wallet).copy()
    wallet.close()
    assert vars(wallet) == before
    for action in (wallet.freeze, wallet.unfreeze, lambda: wallet.change_name(WalletName('Other'))):
        with pytest.raises(WalletClosedError):
            action()
        assert vars(wallet) == before


def test_freeze_rejects_already_frozen_without_changes(wallet):
    wallet.freeze()
    before = vars(wallet).copy()
    with pytest.raises(WalletNotActiveError):
        wallet.freeze()
    assert vars(wallet) == before


def test_unfreeze_rejects_active_without_changes(wallet):
    before = vars(wallet).copy()
    with pytest.raises(WalletNotFrozenError):
        wallet.unfreeze()
    assert vars(wallet) == before


@pytest.mark.parametrize('frozen', [False, True])
def test_rename_open_wallet_touches_timestamp(wallet, frozen):
    if frozen:
        wallet.freeze()
    wallet.updated_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
    wallet.change_name(WalletName('Savings'))
    assert wallet.name.value == 'Savings'
    assert wallet.updated_at.year > 2000
