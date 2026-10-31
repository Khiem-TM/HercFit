"""Symmetric encryption for third-party credentials stored at rest.

Provider refresh tokens grant long-lived access to a user's health data, so they
never sit in the database in plaintext. MultiFernet encrypts with the current
key and still decrypts values written under a retired key during a rotation.
"""
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from core.settings import settings


class TokenCipherUnavailable(RuntimeError):
    """TOKEN_ENCRYPTION_KEY is missing or malformed."""


def _cipher() -> MultiFernet:
    keys = [settings.TOKEN_ENCRYPTION_KEY, *settings.TOKEN_ENCRYPTION_PREVIOUS_KEYS]
    try:
        fernets = [Fernet(key.get_secret_value().encode("ascii")) for key in keys if key and key.get_secret_value()]
    except (ValueError, TypeError) as exc:
        raise TokenCipherUnavailable("TOKEN_ENCRYPTION_KEY must be a urlsafe base64 Fernet key") from exc
    if not fernets:
        raise TokenCipherUnavailable("TOKEN_ENCRYPTION_KEY is not configured")
    return MultiFernet(fernets)


def encrypt_secret(value: str) -> str:
    return _cipher().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    try:
        return _cipher().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise TokenCipherUnavailable("Stored credential cannot be decrypted with the configured keys") from exc


def generate_key() -> str:
    return Fernet.generate_key().decode("ascii")
