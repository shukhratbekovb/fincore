import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from backend.domain.session.entities import Session


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 3, tzinfo=timezone.utc)
        self.ttl = timedelta(days=7)
        self.session = Session.create(
            user_id=uuid4(), ip_address='127.0.0.1',
            now=self.now, ttl=self.ttl,
        )

    def test_creation_uses_supplied_time_and_ttl(self):
        self.assertEqual(self.session.created_at, self.now)
        self.assertEqual(self.session.updated_at, self.now)
        self.assertEqual(self.session.expires_at, self.now + self.ttl)

    def test_expiry_boundary(self):
        expiry = self.session.expires_at
        self.assertFalse(self.session.is_expired(now=expiry - timedelta(microseconds=1)))
        self.assertTrue(self.session.is_expired(now=expiry))
        self.assertTrue(self.session.is_expired(now=expiry + timedelta(microseconds=1)))

    def test_revoke_preserves_first_revocation_time(self):
        revoked_at = self.now + timedelta(minutes=1)
        self.session.revoke(now=revoked_at)
        self.session.revoke(now=revoked_at + timedelta(minutes=1))
        self.assertEqual(self.session.revoked_at, revoked_at)
        self.assertEqual(self.session.updated_at, revoked_at)

    def test_invalid_ttl(self):
        for ttl in (timedelta(0), timedelta(seconds=-1)):
            with self.assertRaises(ValueError):
                Session.create(user_id=uuid4(), ip_address='127.0.0.1', now=self.now, ttl=ttl)

    def test_naive_time_rejected(self):
        now = self.now.replace(tzinfo=None)
        with self.assertRaises(ValueError):
            self.session.is_expired(now=now)
        with self.assertRaises(ValueError):
            self.session.revoke(now=now)
        with self.assertRaises(ValueError):
            Session.create(user_id=uuid4(), ip_address='127.0.0.1', now=now, ttl=self.ttl)
