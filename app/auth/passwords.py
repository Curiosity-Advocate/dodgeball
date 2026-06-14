"""Password hashing with argon2id (NFR-11).

Wraps argon2-cffi's PasswordHasher (argon2id by default). We store only the hash,
which embeds its own random salt and cost parameters; verification is constant-time.
"""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Return an argon2id hash (salt + parameters embedded) for storage."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Return True if the password matches the stored hash, else False."""
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
