"""Secrets at rest (AI provider keys): AES-256-GCM under a key derived from ``BK_MASTER_KEY``.

The associated data binds a ciphertext to where it may be used (provider id + Base URL), so a stored key can
never be decrypted for a different address: changing the URL means entering the key again.
"""

from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from bookkeeper.config import Settings
from bookkeeper.domain.errors import DomainError

VERSION = "v1"


def _key(settings: Settings) -> bytes:
    if settings.master_key is None or not settings.master_key.get_secret_value():
        raise DomainError(
            "INVALID_STATE", "服务器没有设置 BK_MASTER_KEY，不能保存或使用 API 密钥。请在 .env 中设置后重启。"
        )
    raw = settings.master_key.get_secret_value().encode()
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"bookkeeper", info=b"ai-provider-keys").derive(raw)


def seal(plain: str, settings: Settings, bound_to: str) -> str:
    nonce = os.urandom(12)
    sealed = AESGCM(_key(settings)).encrypt(nonce, plain.encode(), bound_to.encode())
    return f"{VERSION}:" + base64.b64encode(nonce + sealed).decode()


def unseal(value: str, settings: Settings, bound_to: str) -> str:
    version, _, payload = value.partition(":")
    if version != VERSION:
        raise DomainError("INVALID_STATE", "密钥的存储格式无法识别，请重新填写密钥。")
    raw = base64.b64decode(payload)
    try:
        return AESGCM(_key(settings)).decrypt(raw[:12], raw[12:], bound_to.encode()).decode()
    except InvalidTag as exc:
        raise DomainError(
            "INVALID_STATE", "密钥无法解开：BK_MASTER_KEY 已更换，或地址变了。请重新填写这个提供商的密钥。"
        ) from exc


def last4(plain: str) -> str:
    return plain.strip()[-4:]
