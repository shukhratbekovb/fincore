from dataclasses import FrozenInstanceError

import pytest

from backend.domain.user.errors import InvalidEmailError, InvalidPasswordError, InvalidUsernameError
from backend.domain.user.value_objects import Email, PasswordCandidate, RawPassword, Username


@pytest.mark.parametrize('value', ['Alice', 'A_123', 'A' * 256])
def test_username_normalizes_valid_values(value):
    assert Username(value).value == value.lower()


@pytest.mark.parametrize('value', ['', 'abcd', 'a' * 257, '1alice', 'alice_', 'ali-ce', 'алиса'])
def test_username_rejects_invalid_values(value):
    with pytest.raises(InvalidUsernameError) as exc:
        Username(value)
    assert exc.value.errors
    assert str(exc.value) == '; '.join(exc.value.errors)


@pytest.mark.parametrize('value', ['Alice@Example.COM', 'alice+tag@example.com'])
def test_email_normalizes_valid_values(value):
    assert Email(value).value == value.lower()


@pytest.mark.parametrize('value', ['', 'alice', '@example.com', 'alice@example', 'alice @example.com', 'a@@example.com'])
def test_email_rejects_invalid_values(value):
    with pytest.raises(InvalidEmailError):
        Email(value)


@pytest.mark.parametrize('value', ['Abcdef1!', 'A' * 253 + 'a1!'])
def test_password_accepts_length_boundaries(value):
    assert RawPassword(value).value == value


@pytest.mark.parametrize('value', ['', 'Aa1!', 'A' * 254 + 'a1!', 'NoDigits!', 'NOLOWER1!', 'noupper1!', 'NoSpecial1'])
def test_password_rejects_policy_violations(value):
    with pytest.raises(InvalidPasswordError) as exc:
        RawPassword(value)
    assert exc.value.errors
    assert str(exc.value) == '; '.join(exc.value.errors)


@pytest.mark.parametrize('factory', [Username, Email, PasswordCandidate, RawPassword])
@pytest.mark.parametrize('value', [None, 123, b'bytes'])
def test_value_objects_reject_non_strings(factory, value):
    with pytest.raises(TypeError):
        factory(value)


def test_value_objects_are_immutable():
    username = Username('alice')
    with pytest.raises(FrozenInstanceError):
        username.value = 'other'


@pytest.mark.parametrize('value', ['x', 'oldpassword', ' ' * 256])
def test_password_candidate_preserves_input_without_new_password_policy(value):
    password = PasswordCandidate(value)
    assert password.value == value
    assert value not in repr(password)


@pytest.mark.parametrize('value', ['', 'x' * 257])
def test_password_candidate_rejects_invalid_length(value):
    with pytest.raises(InvalidPasswordError):
        PasswordCandidate(value)
