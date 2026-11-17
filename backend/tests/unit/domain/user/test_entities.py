from datetime import datetime, timezone

import pytest

from backend.domain.user.entities import User
from backend.domain.user.enums import UserStatusEnum
from backend.domain.user.errors import UserNotPendingConfirmationError
from backend.domain.user.value_objects import Email, HashedPassword, Username


@pytest.fixture
def user():
    return User.register(Username('alice'), Email('alice@example.com'))


def test_registration_starts_pending_without_password(user):
    assert user.status == UserStatusEnum.PENDING_CONFIRMATION
    assert user.password_hash is None
    assert not user.is_active()


def test_confirmation_installs_password_and_activates(user):
    password = HashedPassword('digest')
    user.confirm(password)
    assert user.password_hash == password
    assert user.is_active()


@pytest.mark.parametrize('status', [UserStatusEnum.ACTIVE, UserStatusEnum.SUSPENDED, UserStatusEnum.CLOSED])
def test_confirmation_rejects_other_states_without_mutation(user, status):
    user.status = status
    before = vars(user).copy()
    with pytest.raises(UserNotPendingConfirmationError):
        user.confirm(HashedPassword('digest'))
    assert vars(user) == before


@pytest.mark.parametrize(('action', 'expected'), [('close', UserStatusEnum.CLOSED), ('suspend', UserStatusEnum.SUSPENDED), ('activate', UserStatusEnum.ACTIVE)])
def test_status_actions_touch_timestamp(user, action, expected):
    user.updated_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
    getattr(user, action)()
    assert user.status == expected
    assert user.updated_at.year > 2000


def test_login_records_aware_timestamp(user):
    before = datetime.now(timezone.utc)
    user.login()
    assert before <= user.last_login_at <= datetime.now(timezone.utc)
