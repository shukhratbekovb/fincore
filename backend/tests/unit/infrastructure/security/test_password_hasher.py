from argon2 import PasswordHasher

from backend.domain.user.value_objects import HashedPassword, PasswordCandidate, RawPassword
from backend.infrastructure.security.password_hasher import Argon2PasswordHasher


def test_verify_accepts_existing_password_without_current_creation_policy():
    hasher = Argon2PasswordHasher()
    existing_hash = HashedPassword(PasswordHasher().hash('oldpassword'))
    assert hasher.verify(PasswordCandidate('oldpassword'), existing_hash)
    assert not hasher.verify(PasswordCandidate('wrong'), existing_hash)


def test_new_password_hash_can_be_verified_by_login_candidate():
    hasher = Argon2PasswordHasher()
    password_hash = hasher.hash(RawPassword('Password1!'))
    assert hasher.verify(PasswordCandidate('Password1!'), password_hash)
