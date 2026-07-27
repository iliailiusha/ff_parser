import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_USER_ID = os.getenv("TELEGRAM_USER_ID", "")

KRW_TO_RUB_FALLBACK = float(os.getenv("KRW_TO_RUB", "0.060"))
SGD_TO_RUB_FALLBACK = float(os.getenv("SGD_TO_RUB", "60"))
JPY_TO_RUB_FALLBACK = float(os.getenv("JPY_TO_RUB", "0.55"))
CNY_TO_RUB_FALLBACK = float(os.getenv("CNY_TO_RUB", "11.5"))
USD_TO_RUB = float(os.getenv("USD_TO_RUB", "85"))

API_BASE_URL = os.getenv("API_BASE_URL", "")

TG_PROXY_POOL = [
    p.strip() for p in os.getenv("TG_PROXY_POOL", "").split(",") if p.strip()
]
TG_PROXY_CHECK_INTERVAL = int(os.getenv("TG_PROXY_CHECK_INTERVAL", "300"))

_is_hf = bool(os.getenv("SPACE_ID"))
_storage_dir = os.getenv("STORAGE_DIR", "/data" if _is_hf else str(DATA_DIR))
DB_PATH = Path(_storage_dir) / "storage.db"
os.makedirs(str(DB_PATH.parent), exist_ok=True)

# Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_DEFAULT_TTL = int(os.getenv("REDIS_DEFAULT_TTL", "900"))

# Rate limiting
RATE_LIMIT_DEFAULT_RATE = float(os.getenv("RATE_LIMIT_DEFAULT_RATE", "0.5"))
RATE_LIMIT_DEFAULT_BURST = int(os.getenv("RATE_LIMIT_DEFAULT_BURST", "2"))
SEARCH_RATE_LIMIT_WINDOW = int(os.getenv("SEARCH_RATE_LIMIT_WINDOW", "120"))
SEARCH_RATE_LIMIT_MAX = int(os.getenv("SEARCH_RATE_LIMIT_MAX", "5"))

# Circuit breaker
CIRCUIT_BREAKER_FAILURE_THRESHOLD = int(os.getenv("CIRCUIT_BREAKER_FAILURE_THRESHOLD", "5"))
CIRCUIT_BREAKER_RECOVERY_TIMEOUT = float(os.getenv("CIRCUIT_BREAKER_RECOVERY_TIMEOUT", "60.0"))

# Cookie encryption
COOKIE_ENCRYPTION_KEY = os.getenv("COOKIE_ENCRYPTION_KEY", "")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ──────────────────────────────────────────
# H5 Scraper (public share pages, no auth)
# ──────────────────────────────────────────
# Список прокси (HTTP/SOCKS5). Разделяй запятыми.
# Пример: http://user:pass@1.2.3.4:8080,socks5://user:pass@5.6.7.8:1080
H5_PROXIES = [
    p.strip() for p in os.getenv("H5_PROXIES", "").split(",") if p.strip()
]

# Режим ротации прокси: "roundrobin" или "random"
H5_PROXY_ROTATION = os.getenv("H5_PROXY_ROTATION", "roundrobin")

# Задержка между запросами (сек)
H5_DELAY_MIN = float(os.getenv("H5_DELAY_MIN", "1.0"))
H5_DELAY_MAX = float(os.getenv("H5_DELAY_MAX", "3.0"))

# Количество ретраев при 403/429
H5_MAX_RETRIES = int(os.getenv("H5_MAX_RETRIES", "3"))

# Таймаут запроса (сек)
H5_TIMEOUT = int(os.getenv("H5_TIMEOUT", "30"))

# Максимум конкурентных запросов
H5_CONCURRENCY = int(os.getenv("H5_CONCURRENCY", "5"))

# ──────────────────────────────────────────
# Carousell Scraper
# ──────────────────────────────────────────
CAROUSELL_PROXIES = [
    p.strip() for p in os.getenv("CAROUSELL_PROXIES", "").split(",") if p.strip()
]
CAROUSELL_EXTRA_HEADERS_JSON = os.getenv("CAROUSELL_EXTRA_HEADERS", "{}")
CAROUSELL_COOKIE_MAX_AGE_H = float(os.getenv("CAROUSELL_COOKIE_MAX_AGE_H", "4"))

# Куда сохранять результаты: "csv", "sqlite" или "both"
H5_OUTPUT = os.getenv("H5_OUTPUT", "both")

# Путь для CSV-файла с результатами
H5_CSV_PATH = os.getenv("H5_CSV_PATH", str(DATA_DIR / "h5_results.csv"))

# Путь для SQLite БД (если None — используется основная БД)
H5_SQLITE_PATH = os.getenv("H5_SQLITE_PATH", str(DB_PATH))

# Мобильные User-Agent (iOS/Android / WeChat / Alipay)
MOBILE_USER_AGENTS = [
    # iOS Safari
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/16.6 Mobile/15E148 Safari/604.1",
    # Android Chrome
    "Mozilla/5.0 (Linux; Android 13; SM-S908B) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.6099.230 Mobile Safari/537.36",
    # WeChat iOS
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Mobile/15E148 MicroMessenger/8.0.43",
    # WeChat Android
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Version/4.0 Chrome/120.0.6099.230 Mobile "
    "Safari/537.36 MicroMessenger/8.0.43",
    # Alipay iOS
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Mobile/15E148 AliApp(TxSDK/1.0) AP/10.5.15",
    # Huawei Browser Android
    "Mozilla/5.0 (Linux; Android 12; HarmonyOS; ALN-AL00) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/99.0.4844.88 HuaweiBrowser/14.0.2.311 "
    "Mobile Safari/537.36",
]

# Playwright headless mode (True = без GUI, False = видимый браузер)
H5_HEADLESS = os.getenv("H5_HEADLESS", "true").lower() == "true"

# HTTP Client connection pooling
HTTP_MAX_CONNECTIONS = int(os.getenv("HTTP_MAX_CONNECTIONS", "50"))
HTTP_MAX_KEEPALIVE = int(os.getenv("HTTP_MAX_KEEPALIVE", "20"))
HTTP_KEEPALIVE_TIMEOUT = float(os.getenv("HTTP_KEEPALIVE_TIMEOUT", "30.0"))
