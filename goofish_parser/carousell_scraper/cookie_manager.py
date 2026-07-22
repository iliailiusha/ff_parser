import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from goofish_parser.config import DATA_DIR

logger = logging.getLogger(__name__)

COOKIE_FILE = DATA_DIR / "carousell_cookies.json"
MAX_AGE = timedelta(hours=4)


class CarousellCookieManager:
    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path or COOKIE_FILE

    def load(self) -> dict[str, str]:
        if not self._path.exists():
            logger.info("Carousell cookie file not found: %s", self._path)
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            cookies = data.get("cookies", {})
            created = data.get("created_at", "")
            logger.info("Loaded %d Carousell cookies (created: %s)", len(cookies), created)
            return cookies
        except Exception as e:
            logger.warning("Failed to load Carousell cookies: %s", e)
            return {}

    def save(self, cookies: dict[str, str]) -> None:
        data = {
            "created_at": datetime.now().isoformat(),
            "cookies": cookies,
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            logger.info("Saved %d Carousell cookies to %s", len(cookies), self._path.name)
        except OSError as e:
            logger.error("Failed to save Carousell cookies: %s", e)

    def is_valid(self, cookies: dict[str, str]) -> bool:
        if not cookies:
            return False
        if "cf_clearance" not in cookies:
            logger.debug("Missing cf_clearance cookie")
            return False
        if self._path.exists():
            mtime = datetime.fromtimestamp(self._path.stat().st_mtime)
            age = datetime.now() - mtime
            if age > MAX_AGE:
                logger.info("Carousell cookies expired (%s old)", age)
                return False
        return True

    def clear(self) -> None:
        if self._path.exists():
            self._path.unlink()
            logger.info("Carousell cookie file deleted")
