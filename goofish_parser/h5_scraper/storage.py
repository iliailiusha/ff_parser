import csv
import logging
from datetime import datetime
from typing import Optional

import aiofiles
import aiosqlite

from goofish_parser.config import H5_OUTPUT, H5_CSV_PATH, H5_SQLITE_PATH
from goofish_parser.h5_scraper.parser import H5ItemData

logger = logging.getLogger(__name__)

CSV_FIELDS = [
    "item_id",
    "title",
    "price_cny",
    "original_price_cny",
    "description",
    "images",
    "seller_name",
    "seller_id",
    "condition",
    "location",
    "url",
    "parsed_at",
]


def _build_csv_rows(items: list[H5ItemData], now: str) -> list[str]:
    """Строит строки CSV (включая header если нужно)."""
    import io

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for item in items:
        writer.writerow({
            "item_id": item.item_id,
            "title": item.title,
            "price_cny": item.price_cny,
            "original_price_cny": item.original_price_cny,
            "description": item.description.replace("\n", " ").replace("\r", " "),
            "images": "|".join(item.images),
            "seller_name": item.seller_name,
            "seller_id": item.seller_id,
            "condition": item.condition,
            "location": item.location,
            "url": item.url,
            "parsed_at": now,
        })
    return buf.getvalue().splitlines(keepends=True)


async def _save_csv(items: list[H5ItemData], path: str) -> None:
    """Асинхронно дописывает данные в CSV-файл."""
    file_exists = False
    try:
        async with aiofiles.open(path, mode="r", encoding="utf-8") as f:
            await f.read()
            file_exists = True
    except FileNotFoundError:
        file_exists = False

    now = datetime.now().isoformat()
    lines = _build_csv_rows(items, now)

    if file_exists:
        # пропускаем header (первая строка)
        lines = lines[1:]

    async with aiofiles.open(path, mode="a", encoding="utf-8") as f:
        await f.writelines(lines)

    logger.info("CSV: %d items saved to %s", len(items), path)


async def _save_sqlite(items: list[H5ItemData], path: str) -> None:
    """Асинхронно сохраняет данные в SQLite."""
    async with aiosqlite.connect(path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS h5_items (
                item_id TEXT,
                title TEXT NOT NULL,
                price_cny REAL NOT NULL,
                original_price_cny REAL DEFAULT 0,
                description TEXT DEFAULT '',
                images TEXT DEFAULT '',
                seller_name TEXT DEFAULT '',
                seller_id TEXT DEFAULT '',
                condition TEXT DEFAULT '',
                location TEXT DEFAULT '',
                url TEXT DEFAULT '',
                parsed_at TEXT NOT NULL,
                PRIMARY KEY (item_id, url)
            )
        """)
        await db.commit()

        now = datetime.now().isoformat()
        inserted = 0
        for item in items:
            try:
                await db.execute(
                    """INSERT OR REPLACE INTO h5_items
                       (item_id, title, price_cny, original_price_cny, description,
                        images, seller_name, seller_id, condition, location, url, parsed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        item.item_id,
                        item.title,
                        item.price_cny,
                        item.original_price_cny,
                        item.description,
                        "|".join(item.images),
                        item.seller_name,
                        item.seller_id,
                        item.condition,
                        item.location,
                        item.url,
                        now,
                    ),
                )
                inserted += 1
            except Exception as exc:
                logger.warning("SQLite insert error for %s: %s", item.item_id, exc)

        await db.commit()
        logger.info("SQLite: %d items saved to %s", inserted, path)


async def save_results(
    items: list[H5ItemData],
    csv_path: Optional[str] = None,
    sqlite_path: Optional[str] = None,
    output: Optional[str] = None,
) -> None:
    """Сохраняет результаты в выбранный выходной формат.

    output: "csv" | "sqlite" | "both" (из H5_OUTPUT в config).
    """
    out = (output or H5_OUTPUT).lower()
    csv_p = csv_path or H5_CSV_PATH
    sqlite_p = sqlite_path or H5_SQLITE_PATH

    if not items:
        logger.info("No items to save.")
        return

    if out in ("csv", "both"):
        await _save_csv(items, csv_p)

    if out in ("sqlite", "both"):
        await _save_sqlite(items, sqlite_p)
