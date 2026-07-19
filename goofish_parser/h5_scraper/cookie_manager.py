"""CookieManager — сохранение и загрузка кук сессии Goofish."""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from goofish_parser.config import DATA_DIR
from goofish_parser.services.encryption import get_cookie_encryption

logger = logging.getLogger(__name__)

SESSION_FILE = DATA_DIR / "session_storage.enc"
OLD_SESSION_FILE = DATA_DIR / "session_storage.json"  # legacy plaintext

# Куки, критичные для работы MTOP
REQUIRED_COOKIES = {
    "_m_h5_tk",
    "_m_h5_tk_enc",
    "cna",
    "cookie2",
}

# Куки, желательные для доверия антибота
TRUST_COOKIES = {
    "tfstk",
    "isg",
    "l",
    "mtop_partitioned_detect",
    "x5sec",
}


class CookieManager:
    """Управляет хранением сессионных кук в зашифрованном файле.

    Используется для:
      - Сохранения кук, полученных через BrowserAuthenticator.
      - Загрузки кук перед стартом curl_cffi.
      - Проверки валидности (наличие обязательных кук, не протухли).
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path or SESSION_FILE
        self._encryption = get_cookie_encryption()

    # ── миграция старого формата ──────────────────────────────

    def _migrate_if_needed(self) -> None:
        """Мигрирует старый plaintext session_storage.json в зашифрованный формат."""
        if not OLD_SESSION_FILE.exists() or self._path.exists():
            return
        try:
            raw = OLD_SESSION_FILE.read_text(encoding="utf-8")
            data = json.loads(raw)
            cookies = data.get("cookies", {})
            if cookies:
                logger.info("Migrating %d cookies from legacy session_storage.json", len(cookies))
                self.save(cookies)
                OLD_SESSION_FILE.unlink()
                logger.info("Legacy session file removed")
        except Exception as exc:
            logger.warning("Failed to migrate legacy session: %s", exc)

    # ── загрузка ───────────────────────────────────────────

    def load(self) -> dict[str, str]:
        """Загружает куки из зашифрованного файла.

        Returns:
            Словарь кук, либо пустой словарь если файла нет.
        """
        self._migrate_if_needed()

        if not self._path.exists():
            logger.info("Session file not found: %s", self._path)
            return {}

        try:
            encrypted = self._path.read_bytes()
            data = self._encryption.decrypt(encrypted)
            cookies = data.get("cookies", {})
            created = data.get("created_at", "")
            logger.info(
                "Loaded %d cookies from %s (created: %s)",
                len(cookies), self._path.name, created or "?",
            )
            return cookies
        except Exception as exc:
            logger.warning("Failed to load session: %s", exc)
            return {}

    # ── сохранение ─────────────────────────────────────────

    def save(self, cookies: dict[str, str]) -> None:
        """Сохраняет куки в зашифрованный файл.

        Args:
            cookies: Словарь кук (name -> value).
        """
        data = {
            "created_at": datetime.now().isoformat(),
            "cookies": cookies,
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            encrypted = self._encryption.encrypt(data)
            self._path.write_bytes(encrypted)
            logger.info("Saved %d cookies to %s", len(cookies), self._path.name)
        except OSError as exc:
            logger.error("Failed to save session: %s", exc)

    # ── валидация ──────────────────────────────────────────

    def has_required(self, cookies: dict[str, str]) -> bool:
        """Проверяет наличие всех обязательных кук."""
        missing = REQUIRED_COOKIES - cookies.keys()
        if missing:
            logger.debug("Missing required cookies: %s", missing)
            return False
        return True

    def is_valid(self, cookies: dict[str, str]) -> bool:
        """Проверяет, что куки валидны (существуют + не протухли).

        1. Есть все обязательные куки (_m_h5_tk, _m_h5_tk_enc, cna, cookie2).
        2. _m_h5_tk содержит токен (не пустой).
        3. Куки not expired если есть Expires/Max-Age (на уровне файла мы
           храним только name:value, поэтому проверяем только по времени создания).
        """
        if not cookies:
            return False
        if not self.has_required(cookies):
            return False

        raw_tk = cookies.get("_m_h5_tk", "")
        if "_" not in raw_tk:
            logger.warning("_m_h5_tk has no underscore: %s", raw_tk[:20])
            return False

        token = raw_tk.split("_")[0]
        if len(token) < 8:
            logger.warning("_m_h5_tk token too short: %s", token)
            return False

        # Если файл старше 2 часов — считаем протухшим
        if self._path.exists():
            mtime = datetime.fromtimestamp(self._path.stat().st_mtime)
            age = datetime.now() - mtime
            if age > timedelta(hours=2):
                logger.info("Session file is %s old — expired", age)
                return False

        logger.debug("Session cookies are valid (%d cookies)", len(cookies))
        return True

    # ── очистка ────────────────────────────────────────────

    def clear(self) -> None:
        """Удаляет файл сессии."""
        if self._path.exists():
            self._path.unlink()
            logger.info("Session file deleted: %s", self._path)

    # ── удобство ────────────────────────────────────────────

    def get_token(self, cookies: dict[str, str]) -> str:
        """Извлекает токен из куки _m_h5_tk."""
        raw = cookies.get("_m_h5_tk", "")
        return raw.split("_")[0] if "_" in raw else ""
