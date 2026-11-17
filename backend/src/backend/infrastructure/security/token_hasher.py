import hashlib

from backend.application.verification.interfaces.token_hasher import ITokenHasher


class TokenHasher(ITokenHasher):
    def hash(self, token: str) -> str:
        return hashlib.sha256(token.encode('utf-8')).hexdigest()
