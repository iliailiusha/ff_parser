import json
import sqlite3
import threading
from datetime import datetime
from typing import Optional

from goofish_parser.config import DB_PATH
from goofish_parser.scraper.models import GoofishItem, ScoredItem, ALL_PLATFORMS

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
            item_id TEXT NOT NULL,
            title TEXT NOT NULL,
            price_krw REAL NOT NULL,
            url TEXT NOT NULL,
            condition TEXT DEFAULT '',
            location TEXT DEFAULT '',
            badge TEXT DEFAULT '',
            search_query TEXT DEFAULT '',
            source TEXT DEFAULT 'fruitsfamily',
            country TEXT DEFAULT '',
            currency TEXT DEFAULT '₩',
            found_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scored_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id TEXT NOT NULL,
            market_avg_krw REAL NOT NULL,
            discount_pct REAL NOT NULL,
            price_rub REAL NOT NULL,
            market_avg_rub REAL NOT NULL,
            score REAL NOT NULL,
            source TEXT DEFAULT 'fruitsfamily',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS price_cache (
            cache_key TEXT PRIMARY KEY,
            avg_price REAL NOT NULL,
            sample_count INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rate_cache (
            cache_key TEXT PRIMARY KEY,
            avg_price REAL NOT NULL,
            sample_count INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER NOT NULL,
            setting_key TEXT NOT NULL,
            setting_value TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, setting_key)
        );
    """)

    # migrate: add columns if missing
    try:
        conn.execute("ALTER TABLE items ADD COLUMN source TEXT DEFAULT 'fruitsfamily'")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE items ADD COLUMN country TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE items ADD COLUMN currency TEXT DEFAULT '₩'")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE scored_items ADD COLUMN source TEXT DEFAULT 'fruitsfamily'")
    except sqlite3.OperationalError:
        pass

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
                   (item_id, title, price_krw, url, condition, location, badge, search_query, source, country, currency, found_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item.item_id, item.title, item.price_cny, item.url,
                 item.condition, item.location, item.badge, search_query,
                 item.source, item.country, item.currency, now),
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
                   (item_id, market_avg_krw, discount_pct, price_rub, market_avg_rub, score, source, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (s.item.item_id, s.market_avg_cny, s.discount_pct,
                 s.price_rub, s.market_avg_rub, s.score, s.item.source, now),
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


def get_rate_cache(cache_key: str) -> Optional[tuple[str, float]]:
    conn = _get_conn()
    row = conn.execute(
        "SELECT updated_at, avg_price FROM rate_cache WHERE cache_key = ?",
        (cache_key,),
    ).fetchone()
    if row:
        return row["updated_at"][:10], row["avg_price"]
    return None


def set_rate_cache(cache_key: str, rate: float) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO rate_cache (cache_key, avg_price, sample_count, updated_at) VALUES (?, ?, 1, ?)",
        (cache_key, rate, datetime.now().isoformat()),
    )
    conn.commit()


def get_user_setting(user_id: int, setting_key: str, default: str = "") -> str:
    conn = _get_conn()
    row = conn.execute(
        "SELECT setting_value FROM user_settings WHERE user_id = ? AND setting_key = ?",
        (user_id, setting_key),
    ).fetchone()
    return row["setting_value"] if row else default


def set_user_setting(user_id: int, setting_key: str, setting_value: str) -> None:
    conn = _get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO user_settings (user_id, setting_key, setting_value, updated_at)
           VALUES (?, ?, ?, ?)""",
        (user_id, setting_key, setting_value, datetime.now().isoformat()),
    )
    conn.commit()


def get_disabled_platforms(user_id: int) -> set[str]:
    val = get_user_setting(user_id, "disabled_platforms", "")
    if not val:
        return set()
    return set(val.split(","))


def set_disabled_platforms(user_id: int, platforms: set[str]) -> None:
    set_user_setting(user_id, "disabled_platforms", ",".join(sorted(platforms)))


def get_disabled_countries(user_id: int) -> set[str]:
    val = get_user_setting(user_id, "disabled_countries", "")
    if not val:
        return set()
    return set(val.split(","))


def set_disabled_countries(user_id: int, countries: set[str]) -> None:
    set_user_setting(user_id, "disabled_countries", ",".join(sorted(countries)))


def get_enabled_platforms(user_id: int) -> list[str]:
    disabled_platforms = get_disabled_platforms(user_id)
    disabled_countries = get_disabled_countries(user_id)

    from goofish_parser.scraper.models import COUNTRY_PLATFORMS, ALL_PLATFORMS

    # if a country is disabled, all its platforms are disabled
    result = []
    for p in ALL_PLATFORMS:
        if p in disabled_platforms:
            continue
        # check if platform's country is disabled
        for country, platforms in COUNTRY_PLATFORMS.items():
            if p in platforms and country in disabled_countries:
                break
        else:
            result.append(p)
    return result


def get_recent_deals(limit: int = 20) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        """SELECT i.*, s.discount_pct, s.market_avg_krw, s.price_rub, s.market_avg_rub, s.score
           FROM scored_items s
           JOIN items i ON i.item_id = s.item_id
           ORDER BY s.discount_pct DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def increment_brand_freq(user_id: int, brand: str) -> None:
    conn = _get_conn()
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO user_settings (user_id, setting_key, setting_value, updated_at)
           VALUES (?, ?, 1, ?)
           ON CONFLICT(user_id, setting_key) DO UPDATE SET
               setting_value = CAST(CAST(setting_value AS INTEGER) + 1 AS TEXT),
               updated_at = ?""",
        (user_id, f"brand_freq:{brand}", now, now),
    )
    conn.commit()


def get_top_brands(user_id: int, limit: int = 5) -> list[str]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT setting_key, CAST(setting_value AS INTEGER) as freq FROM user_settings WHERE user_id = ? AND setting_key LIKE 'brand_freq:%' ORDER BY freq DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [r["setting_key"].replace("brand_freq:", "") for r in rows]


def increment_type_freq(user_id: int, item_type: str) -> None:
    conn = _get_conn()
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO user_settings (user_id, setting_key, setting_value, updated_at)
           VALUES (?, ?, 1, ?)
           ON CONFLICT(user_id, setting_key) DO UPDATE SET
               setting_value = CAST(CAST(setting_value AS INTEGER) + 1 AS TEXT),
               updated_at = ?""",
        (user_id, f"type_freq:{item_type}", now, now),
    )
    conn.commit()


def get_top_types(user_id: int, limit: int = 5) -> list[str]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT setting_key, CAST(setting_value AS INTEGER) as freq FROM user_settings WHERE user_id = ? AND setting_key LIKE 'type_freq:%' ORDER BY freq DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [r["setting_key"].replace("type_freq:", "") for r in rows]


def save_model(user_id: int, brand: str, item_type: str, model: str) -> None:
    conn = _get_conn()
    now = datetime.now().isoformat()
    key = f"saved_model:{brand}|{item_type}|{model}"
    conn.execute(
        """INSERT OR REPLACE INTO user_settings (user_id, setting_key, setting_value, updated_at)
           VALUES (?, ?, ?, ?)""",
        (user_id, key, model, now),
    )
    conn.commit()


def get_saved_models(user_id: int, brand: str, item_type: str) -> list[str]:
    conn = _get_conn()
    prefix = f"saved_model:{brand}|{item_type}|"
    rows = conn.execute(
        "SELECT setting_value FROM user_settings WHERE user_id = ? AND setting_key LIKE ? ORDER BY updated_at DESC",
        (user_id, f"{prefix}%"),
    ).fetchall()
    return [r["setting_value"] for r in rows]


def delete_model(user_id: int, brand: str, item_type: str, model: str) -> None:
    conn = _get_conn()
    key = f"saved_model:{brand}|{item_type}|{model}"
    conn.execute(
        "DELETE FROM user_settings WHERE user_id = ? AND setting_key = ?",
        (user_id, key),
    )
    conn.commit()


def get_disabled_brand_recs(user_id: int) -> set[str]:
    val = get_user_setting(user_id, "disabled_brand_recs", "")
    if not val:
        return set()
    return set(val.split(","))


def set_disabled_brand_recs(user_id: int, brands: set[str]) -> None:
    set_user_setting(user_id, "disabled_brand_recs", ",".join(sorted(brands)))
