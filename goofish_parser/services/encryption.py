import base64
import json
import os
from pathlib import Path
from typing import Any, Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from goofish_parser.config import COOKIE_ENCRYPTION_KEY, DATA_DIR


class CookieEncryption:
    def __init__(self, password: Optional[str] = None):
        if password is None:
            password = COOKIE_ENCRYPTION_KEY or "default-dev-key-change-in-production"
        self._fernet = self._derive_fernet(password)

    def _derive_fernet(self, password: str) -> Fernet:
        salt = b"goofish-cookie-salt-v1"
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100_000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return Fernet(key)

    def encrypt(self, data: dict[str, Any]) -> bytes:
        json_data = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()
        return self._fernet.encrypt(json_data)

    def decrypt(self, encrypted: bytes) -> dict[str, Any]:
        json_data = self._fernet.decrypt(encrypted)
        return json.loads(json_data.decode())

    def encrypt_to_file(self, data: dict[str, Any], path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        encrypted = self.encrypt(data)
        path.write_bytes(encrypted)

    def decrypt_from_file(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        encrypted = path.read_bytes()
        return self.decrypt(encrypted)


_cookie_encryption: Optional[CookieEncryption] = None


def get_cookie_encryption() -> CookieEncryption:
    global _cookie_encryption
    if _cookie_encryption is None:
        _cookie_encryption = CookieEncryption()
    return _cookie_encryption