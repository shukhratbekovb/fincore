import secrets
import string

from backend.application.auth.interfaces.password_generator import IPasswordGenerator
from backend.domain.user.value_objects import RawPassword


class PasswordGenerator(IPasswordGenerator):
    def generate(self) -> RawPassword:
        groups = (
            string.ascii_lowercase,
            string.ascii_uppercase,
            string.digits,
            string.punctuation,
        )
        alphabet = "".join(groups)

        characters = [secrets.choice(group) for group in groups]
        characters.extend(secrets.choice(alphabet) for _ in range(12))

        secrets.SystemRandom().shuffle(characters)

        return RawPassword(value="".join(characters))
