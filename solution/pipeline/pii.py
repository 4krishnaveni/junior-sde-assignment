from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet


class PiiKeyMismatch(RuntimeError):
    pass


class PiiVault:
    def __init__(self, secret: bytes) -> None:
        self._hash_key = hmac.new(
            secret, b"au/phone-hash/v1", hashlib.sha256).digest()
        enc_key = hmac.new(secret, b"au/field-encryption/v1",
                           hashlib.sha256).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(enc_key))

    def phone_hash(self, canonical_phone: str) -> str:
        return hmac.digest(self._hash_key, canonical_phone.encode("ascii"), "sha256").hex()

    def fingerprint(self) -> str:
        return hmac.digest(self._hash_key, b"fingerprint", "sha256").hex()[:16]

    def encrypt_json(self, obj: dict) -> str:
        return self._fernet.encrypt(json.dumps(obj, sort_keys=True).encode("utf-8")).decode("ascii")

    def decrypt_json(self, token: str) -> dict:
        return json.loads(self._fernet.decrypt(token.encode("ascii")).decode("utf-8"))


def load_secret(db_path) -> bytes:
    env = os.environ.get("AU_PII_KEY")
    if env:
        return env.encode("utf-8")
    key_path = Path(str(db_path) + ".key")
    if key_path.exists():
        return key_path.read_text(encoding="ascii").strip().encode("ascii")
    secret = secrets.token_hex(32)
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        handle.write(secret)
    return secret.encode("ascii")
