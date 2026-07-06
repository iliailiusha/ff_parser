import logging
from datetime import date
from typing import Optional

import requests

from goofish_parser.storage.db import get_rate_cache, set_rate_cache
from goofish_parser.config import KRW_TO_RUB_FALLBACK

CBR_URL = "https://www.cbr-xml-daily.ru/daily_json.js"
logger = logging.getLogger(__name__)


def fetch_krw_rate() -> Optional[float]:
    try:
        resp = requests.get(CBR_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        krw = data["Valute"]["KRW"]
        value = krw["Value"]
        nominal = krw["Nominal"]
        rate = value / nominal
        logger.info(f"KRW rate from CBR: {rate:.4f} RUB (nominal={nominal}, value={value})")
        return round(rate, 4)
    except Exception as e:
        logger.warning(f"Failed to fetch KRW rate from CBR: {e}")
        return None


def get_krw_to_rub() -> float:
    today = date.today().isoformat()
    cached = get_rate_cache("KRW_TO_RUB")
    if cached:
        cached_date, rate = cached
        if cached_date == today:
            return rate

    rate = fetch_krw_rate()
    if rate is not None:
        set_rate_cache("KRW_TO_RUB", rate)
        return rate

    if cached:
        _, rate = cached
        logger.info(f"Using stale cached KRW rate: {rate}")
        return rate

    logger.info(f"Using fallback KRW rate: {KRW_TO_RUB_FALLBACK}")
    return KRW_TO_RUB_FALLBACK


def update_rate_daily() -> float:
    rate = fetch_krw_rate()
    if rate is None:
        rate = get_krw_to_rub()
    return rate
