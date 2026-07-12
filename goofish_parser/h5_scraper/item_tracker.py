"""ItemTracker — дедупликация объявлений.

Хранит уже увиденные itemId в data/seen_items.json.
В памяти держит как set для O(1) lookup.
"""
import json
import logging
from pathlib import Path
from typing import Any, Optional

from goofish_parser.config import DATA_DIR

logger = logging.getLogger(__name__)

SEEN_PATH = DATA_DIR / "seen_items.json"


class ItemTracker:
    """Трекер увиденных itemId для исключения дубликатов."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path or SEEN_PATH
        self._seen: set[str] = set()
        self._load()

    def filter_new_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Принимает список айтемов, возвращает только новые (не виданные ранее).

        Новые айтемы сразу сохраняются в кэш.
        """
        new: list[dict[str, Any]] = []
        for item in items:
            item_id = str(item.get("itemId") or item.get("item_id") or "")
            if not item_id:
                continue
            if item_id not in self._seen:
                self._seen.add(item_id)
                new.append(item)

        if new:
            self._save()
            logger.info(
                "[TRACKER] Incoming items: %d, New: %d, Total seen: %d",
                len(items),
                len(new),
                len(self._seen),
            )

        return new

    def is_seen(self, item_id: str) -> bool:
        return item_id in self._seen

    def mark_seen(self, item_id: str) -> None:
        if item_id not in self._seen:
            self._seen.add(item_id)
            self._save()

    def count(self) -> int:
        return len(self._seen)

    def _load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
                self._seen = set(str(x) for x in data)
            logger.info("Loaded %d seen items from %s", len(self._seen), self._path)
        except (FileNotFoundError, json.JSONDecodeError):
            self._seen = set()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(list(self._seen), f, indent=2, ensure_ascii=False)
