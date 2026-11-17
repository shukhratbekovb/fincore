from unittest.mock import Mock

import pytest

from backend.domain.wallet.value_objects import WALLET_NUMBER_LENGTH, WalletNumber
from backend.infrastructure.wallet import number_generator
from backend.infrastructure.wallet.number_generator import RandomWalletNumberGenerator


@pytest.mark.parametrize(('random_value', 'expected'), [
    (0, '0' * 20),
    (1, '0' * 19 + '1'),
    (10 ** 20 - 1, '9' * 20),
])
def test_generator_formats_random_value_without_losing_zeros(monkeypatch, random_value, expected):
    random_source = Mock(return_value=random_value)
    monkeypatch.setattr(number_generator.secrets, 'randbelow', random_source)
    result = RandomWalletNumberGenerator().generate()
    assert result == WalletNumber(expected)
    random_source.assert_called_once_with(10 ** WALLET_NUMBER_LENGTH)


def test_generator_uses_fresh_entropy_each_time(monkeypatch):
    random_source = Mock(side_effect=[1, 2])
    monkeypatch.setattr(number_generator.secrets, 'randbelow', random_source)
    generator = RandomWalletNumberGenerator()
    assert generator.generate() != generator.generate()
    assert random_source.call_count == 2


def test_real_generator_returns_valid_number():
    number = RandomWalletNumberGenerator().generate()
    assert isinstance(number, WalletNumber)
    assert len(number.value) == WALLET_NUMBER_LENGTH
    assert number.value.isascii() and number.value.isdigit()
