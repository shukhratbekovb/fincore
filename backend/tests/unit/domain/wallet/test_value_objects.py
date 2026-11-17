from dataclasses import FrozenInstanceError

import pytest

from backend.domain.wallet.errors import InvalidWalletNameError, InvalidWalletNumberError
from backend.domain.wallet.value_objects import WalletName, WalletNumber


@pytest.mark.parametrize(('value', 'expected'), [
    ('  Main wallet  ', 'Main wallet'), ('Кошелёк', 'Кошелёк'),
    ('A', 'A'), ('A' * 64, 'A' * 64), (' My  wallet ', 'My  wallet'),
])
def test_wallet_name_normalizes_edges(value, expected):
    assert WalletName(value).value == expected


@pytest.mark.parametrize('value', ['', '   ', '\t\n', 'A' * 65])
def test_invalid_wallet_name(value):
    with pytest.raises(InvalidWalletNameError):
        WalletName(value)


@pytest.mark.parametrize('value', ['0' * 20, '12345678901234567890', '00000000000000000001'])
def test_wallet_number_preserves_digits_and_leading_zeros(value):
    assert WalletNumber(value).value == value


@pytest.mark.parametrize('value', [
    '', '1' * 19, '1' * 21, 'a' * 20, '١' * 20, '１' * 20,
    ' ' + '1' * 19, '+' + '1' * 19, '1' * 19 + '\n',
])
def test_invalid_wallet_number(value):
    with pytest.raises(InvalidWalletNumberError):
        WalletNumber(value)


@pytest.mark.parametrize('factory', [WalletName, WalletNumber])
@pytest.mark.parametrize('value', [None, 123, b'123'])
def test_value_objects_reject_non_strings(factory, value):
    with pytest.raises(TypeError):
        factory(value)


@pytest.mark.parametrize('obj', [WalletName('Main'), WalletNumber('0' * 20)])
def test_value_objects_are_immutable(obj):
    with pytest.raises(FrozenInstanceError):
        obj.value = 'changed'
