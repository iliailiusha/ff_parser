"""FiltersManager — управление кастомными фильтрами пользователей.

Хранит фильтры в data/user_filters.json.
Максимум 50 активных фильтров в системе.
"""
import json
import logging
from pathlib import Path
from typing import Any, Optional

from goofish_parser.config import DATA_DIR

logger = logging.getLogger(__name__)

MAX_FILTERS = 50
FILTERS_PATH = DATA_DIR / "user_filters.json"


class FiltersManager:
    """Менеджер фильтров: CRUD + guard на 50 фильтров."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path or FILTERS_PATH
        self._filters: list[dict[str, Any]] = []
        self._load()

    def add_filter(
        self,
        user_id: int,
        keyword: str,
        min_price: float = 0.0,
        max_price: float = 1_000_000.0,
    ) -> None:
        if len(self._filters) >= MAX_FILTERS:
            raise RuntimeError(
                f"Maximum {MAX_FILTERS} filters reached, cannot add more"
            )
        filter_: dict[str, Any] = {
            "user_id": user_id,
            "keyword": keyword,
            "min_price": min_price,
            "max_price": max_price,
        }
        self._filters.append(filter_)
        self._save()
        logger.info("Filter added: user=%d keyword=%s", user_id, keyword)

    def remove_filter(self, user_id: int, keyword: str) -> bool:
        before = len(self._filters)
        self._filters = [
            f
            for f in self._filters
            if not (f["user_id"] == user_id and f["keyword"] == keyword)
        ]
        removed = len(self._filters) < before
        if removed:
            self._save()
            logger.info("Filter removed: user=%d keyword=%s", user_id, keyword)
        return removed

    def get_all_active_filters(self) -> list[dict[str, Any]]:
        return list(self._filters)

    def _load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as f:
                self._filters = json.load(f)
            logger.info("Loaded %d filters from %s", len(self._filters), self._path)
        except (FileNotFoundError, json.JSONDecodeError):
            self._filters = []

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._filters, f, indent=2, ensure_ascii=False)
