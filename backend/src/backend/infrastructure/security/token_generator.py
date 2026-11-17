import secrets

from backend.application.verification.interfaces.token_generator import ITokenGenerator


class TokenGenerator(ITokenGenerator):
    def generate(self) -> str:
        return secrets.token_urlsafe(64)
