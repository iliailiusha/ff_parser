import json
import sqlite3
import threading
from datetime import datetime
from typing import Optional

from goofish_parser.config import DB_PATH
from goofish_parser.scraper.models import GoofishItem, ScoredItem

_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(str(DB_PATH))
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def init_db() -> None:
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS search_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand TEXT NOT NULL,
            item_type TEXT NOT NULL,
            price_min REAL,
            price_max REAL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            price_cny REAL NOT NULL,
            url TEXT NOT NULL,
            condition TEXT DEFAULT '',
            location TEXT DEFAULT '',
            badge TEXT DEFAULT '',
            search_query TEXT DEFAULT '',
            found_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scored_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id TEXT UNIQUE NOT NULL,
            market_avg_cny REAL NOT NULL,
            discount_pct REAL NOT NULL,
            price_rub REAL NOT NULL,
            market_avg_rub REAL NOT NULL,
            score REAL NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS price_cache (
            cache_key TEXT PRIMARY KEY,
            avg_price REAL NOT NULL,
            sample_count INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    conn.commit()


def save_search(brand: str, item_type: str, price_min: Optional[float], price_max: Optional[float]) -> int:
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO search_history (brand, item_type, price_min, price_max, created_at) VALUES (?, ?, ?, ?, ?)",
        (brand, item_type, price_min, price_max, datetime.now().isoformat()),
    )
    conn.commit()
    return cur.lastrowid


def save_items(items: list[GoofishItem], search_query: str = "") -> None:
    conn = _get_conn()
    now = datetime.now().isoformat()
    for item in items:
        try:
            conn.execute(
                """INSERT OR IGNORE INTO items
                   (item_id, title, price_cny, url, condition, location, badge, search_query, found_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item.item_id, item.title, item.price_cny, item.url,
                 item.condition, item.location, item.badge, search_query, now),
            )
        except sqlite3.IntegrityError:
            pass
    conn.commit()


def save_scored_items(scored: list[ScoredItem]) -> None:
    conn = _get_conn()
    now = datetime.now().isoformat()
    for s in scored:
        try:
            conn.execute(
                """INSERT OR REPLACE INTO scored_items
                   (item_id, market_avg_cny, discount_pct, price_rub, market_avg_rub, score, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (s.item.item_id, s.market_avg_cny, s.discount_pct,
                 s.price_rub, s.market_avg_rub, s.score, now),
            )
        except sqlite3.IntegrityError:
            pass
    conn.commit()


def get_price_cache(cache_key: str) -> Optional[tuple[float, int]]:
    conn = _get_conn()
    row = conn.execute(
        "SELECT avg_price, sample_count FROM price_cache WHERE cache_key = ?",
        (cache_key,),
    ).fetchone()
    if row:
        return row["avg_price"], row["sample_count"]
    return None


def set_price_cache(cache_key: str, avg_price: float, sample_count: int) -> None:
    conn = _get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO price_cache (cache_key, avg_price, sample_count, updated_at)
           VALUES (?, ?, ?, ?)""",
        (cache_key, avg_price, sample_count, datetime.now().isoformat()),
    )
    conn.commit()


def get_recent_deals(limit: int = 20) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        """SELECT i.*, s.discount_pct, s.market_avg_cny, s.price_rub, s.market_avg_rub, s.score
           FROM scored_items s
           JOIN items i ON i.item_id = s.item_id
           ORDER BY s.discount_pct DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
