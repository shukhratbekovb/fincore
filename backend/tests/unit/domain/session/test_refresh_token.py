from datetime import timedelta
from uuid import uuid4

import pytest

from backend.domain.session.entities import RefreshToken
from backend.domain.session.errors import InvalidRefreshTokenError


@pytest.mark.parametrize('state', ['used', 'expired', 'expiry_boundary'])
def test_unusable_token_cannot_rotate(now, state):
    token = RefreshToken(session_id=uuid4(), token_hash='secret', expires_at=now + timedelta(hours=1))
    if state == 'used':
        token = RefreshToken(session_id=token.session_id, token_hash='secret', expires_at=token.expires_at, used_at=now)
    else:
        token.expires_at = now if state == 'expiry_boundary' else now - timedelta(seconds=1)
    before = vars(token).copy()
    with pytest.raises(InvalidRefreshTokenError):
        token.rotate(replacement_id=uuid4(), now=now)
    assert vars(token) == before
    assert 'secret' not in repr(token)
