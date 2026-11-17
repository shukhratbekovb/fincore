import base64
import hashlib
import hmac
import json
from datetime import timedelta, timezone
from uuid import uuid4

import pytest

from backend.application.share.dtos.pagination import CursorPosition
from backend.application.share.errors import InvalidCursorError
from backend.infrastructure.pagination.cursor import HMACCursorCodec

TEST_KEY = b'cursor-test-key-only-not-a-secret-1234'


@pytest.fixture
def codec():
    return HMACCursorCodec(key=TEST_KEY)


def signed_payload(value):
    payload = value if isinstance(value, bytes) else json.dumps(value).encode()
    signature = hmac.digest(TEST_KEY, payload, 'sha256')
    return '.'.join(base64.urlsafe_b64encode(part).rstrip(b'=').decode() for part in (payload, signature))


def test_roundtrip_normalizes_time_without_losing_microseconds(codec, now):
    position = CursorPosition(timestamp=now.replace(microsecond=123456).astimezone(timezone(timedelta(hours=5))), id=uuid4())
    token = codec.encode(position, context='actor-and-filters')
    restored = codec.decode(token, context='actor-and-filters')
    assert restored == position
    assert restored.timestamp.utcoffset() == timedelta(0)


def test_cursor_cannot_be_used_in_other_context(codec, now):
    token = codec.encode(CursorPosition(timestamp=now, id=uuid4()), context='user-a')
    with pytest.raises(InvalidCursorError):
        codec.decode(token, context='user-b')


def test_cursor_cannot_be_used_with_other_signing_key(codec, now):
    token = codec.encode(CursorPosition(timestamp=now, id=uuid4()), context='same')
    with pytest.raises(InvalidCursorError):
        HMACCursorCodec(b'other-test-signing-key-12345678901').decode(token, context='same')


def test_payload_tampering_is_rejected(codec, now):
    token = codec.encode(CursorPosition(timestamp=now, id=uuid4()), context='same')
    payload, signature = token.split('.')
    data = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
    data['id'] = str(uuid4())
    changed = base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b'=').decode()
    with pytest.raises(InvalidCursorError):
        codec.decode(changed + '.' + signature, context='same')


@pytest.mark.parametrize('token', [None, 1, '', 'x' * 2049, 'abc', 'a.b.c', '!!!!.AAAA', '.'])
def test_malformed_cursor_is_rejected(codec, token):
    with pytest.raises(InvalidCursorError):
        codec.decode(token, context='same')


@pytest.mark.parametrize('change', [
    'not_object', 'missing_field', 'extra_field', 'version', 'bool_version',
    'wrong_context', 'invalid_time', 'naive_time', 'invalid_id', 'id_type',
])
def test_signed_invalid_payload_is_rejected(codec, now, change):
    payload = {
        'v': 1, 'ctx': hashlib.sha256(b'same').hexdigest(),
        'timestamp': now.isoformat(), 'id': str(uuid4()),
    }
    if change == 'not_object':
        payload = []
    elif change == 'missing_field':
        del payload['id']
    elif change == 'extra_field':
        payload['other'] = 1
    else:
        changes = {
            'version': ('v', 2), 'bool_version': ('v', True), 'wrong_context': ('ctx', 'other'),
            'invalid_time': ('timestamp', 'not-a-date'), 'naive_time': ('timestamp', now.replace(tzinfo=None).isoformat()),
            'invalid_id': ('id', 'not-a-uuid'), 'id_type': ('id', 1),
        }
        key, value = changes[change]
        payload[key] = value
    with pytest.raises(InvalidCursorError):
        codec.decode(signed_payload(payload), context='same')


@pytest.mark.parametrize('payload', [b'not-json', b'\xff'])
def test_invalid_json_or_encoding_is_rejected(codec, payload):
    with pytest.raises(InvalidCursorError):
        codec.decode(signed_payload(payload), context='same')


@pytest.mark.parametrize('key', [None, 'string', b'', b'x' * 31])
def test_signing_key_must_have_at_least_32_bytes(key):
    with pytest.raises(ValueError):
        HMACCursorCodec(key)


def test_signing_key_is_hidden_from_repr(codec):
    assert TEST_KEY.decode() not in repr(codec)


@pytest.mark.parametrize('field', ['timestamp', 'id'])
def test_cursor_position_rejects_invalid_types(now, field):
    values = {'timestamp': now, 'id': uuid4(), field: None}
    with pytest.raises(InvalidCursorError):
        CursorPosition(**values)
