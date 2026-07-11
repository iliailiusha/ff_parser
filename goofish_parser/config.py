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
USD_TO_RUB = float(os.getenv("USD_TO_RUB", "85"))

API_BASE_URL = os.getenv("API_BASE_URL", "")

DB_PATH = DATA_DIR / "storage.db"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
