from datetime import timedelta
from uuid import uuid4

import pytest

from backend.domain.verification.entities import VerificationChallenge
from backend.domain.verification.enums import VerificationPurpose
from backend.domain.verification.errors import VerificationChallengeAlreadyUsedError, VerificationChallengeExpiredError, VerificationChallengePurposeMismatchError


@pytest.fixture
def challenge(now):
    return VerificationChallenge(user_id=uuid4(), purpose=VerificationPurpose.REGISTRATION,
                                 token_hash='secret-digest', expires_at=now + timedelta(minutes=10))


def test_success_and_reuse(challenge, now):
    challenge.use(purpose=VerificationPurpose.REGISTRATION, now=now)
    assert challenge.used_at == now
    with pytest.raises(VerificationChallengeAlreadyUsedError):
        challenge.use(purpose=VerificationPurpose.REGISTRATION, now=now)
    assert challenge.used_at == now
    assert 'secret-digest' not in repr(challenge)


@pytest.mark.parametrize('offset', [0, 1])
def test_expiry_boundary(challenge, offset):
    with pytest.raises(VerificationChallengeExpiredError):
        challenge.use(purpose=VerificationPurpose.REGISTRATION, now=challenge.expires_at + timedelta(seconds=offset))
    assert challenge.used_at is None


def test_wrong_purpose_does_not_consume(challenge, now):
    with pytest.raises(VerificationChallengePurposeMismatchError):
        challenge.use(purpose=VerificationPurpose.PASSWORD_RESET, now=now)
    assert challenge.used_at is None


def test_restores_consumed_challenge(challenge, now):
    restored = VerificationChallenge(user_id=challenge.user_id, purpose=challenge.purpose,
                                    token_hash=challenge.token_hash, expires_at=challenge.expires_at, used_at=now)
    with pytest.raises(VerificationChallengeAlreadyUsedError):
        restored.use(purpose=restored.purpose, now=now)


def test_rejects_naive_time(challenge, now):
    with pytest.raises(ValueError):
        challenge.use(purpose=challenge.purpose, now=now.replace(tzinfo=None))
    assert challenge.used_at is None
