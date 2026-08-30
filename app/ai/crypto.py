from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


class SecretDecryptionError(ValueError):
    pass


def _fernet(secret: str) -> Fernet:
    if not secret:
        raise ValueError("application secret must not be empty")
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str, application_secret: str) -> str:
    if not value:
        raise ValueError("secret must not be empty")
    return _fernet(application_secret).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str, application_secret: str) -> str:
    try:
        return _fernet(application_secret).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise SecretDecryptionError("configured secret cannot be decrypted") from exc


def encrypt_api_key(api_key: str, application_secret: str) -> str:
    return encrypt_secret(api_key, application_secret)


def decrypt_api_key(ciphertext: str, application_secret: str) -> str:
    return decrypt_secret(ciphertext, application_secret)
