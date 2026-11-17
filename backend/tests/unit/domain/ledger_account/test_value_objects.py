from dataclasses import FrozenInstanceError

import pytest

from backend.domain.ledger_account.errors import InvalidLedgerAccountCodeError
from backend.domain.ledger_account.value_objects import LedgerAccountCode


@pytest.mark.parametrize('value', ['A', 'A' * 80, 'SYS:SIM_FUNDING:USD', 'WALLET:abc-123:EUR'])
def test_valid_code_is_preserved(value):
    assert LedgerAccountCode(value).value == value


@pytest.mark.parametrize('value', ['', 'A' * 81, ' SYS:USD', 'SYS:USD ', ':USD', 'A B', 'A\n', 'СЧЕТ:USD', 'A/B'])
def test_invalid_code(value):
    with pytest.raises(InvalidLedgerAccountCodeError):
        LedgerAccountCode(value)


@pytest.mark.parametrize('value', [None, 1, b'SYS:USD'])
def test_code_rejects_non_strings(value):
    with pytest.raises(TypeError):
        LedgerAccountCode(value)


def test_code_is_immutable():
    code = LedgerAccountCode('SYS:SIM_FUNDING:USD')
    with pytest.raises(FrozenInstanceError):
        code.value = 'OTHER'
