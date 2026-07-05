import logging
from datetime import date
from typing import Optional

import requests

from goofish_parser.storage.db import get_rate_cache, set_rate_cache

CBR_URL = "https://www.cbr-xml-daily.ru/daily_json.js"
FALLBACK_RATE = 12.0
logger = logging.getLogger(__name__)


def fetch_cny_rate() -> Optional[float]:
    try:
        resp = requests.get(CBR_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        cny = data["Valute"]["CNY"]
        value = cny["Value"]
        nominal = cny["Nominal"]
        rate = value / nominal
        logger.info(f"CNY rate from CBR: {rate:.2f} RUB (nominal={nominal}, value={value})")
        return round(rate, 2)
    except Exception as e:
        logger.warning(f"Failed to fetch CNY rate from CBR: {e}")
        return None


def get_cny_to_rub() -> float:
    today = date.today().isoformat()
    cached = get_rate_cache("CNY_TO_RUB")
    if cached:
        cached_date, rate = cached
        if cached_date == today:
            return rate

    rate = fetch_cny_rate()
    if rate is not None:
        set_rate_cache("CNY_TO_RUB", rate)
        return rate

    if cached:
        _, rate = cached
        logger.info(f"Using stale cached CNY rate: {rate}")
        return rate

    logger.info(f"Using fallback CNY rate: {FALLBACK_RATE}")
    return FALLBACK_RATE


def update_rate_daily() -> float:
    rate = fetch_cny_rate()
    if rate is None:
        rate = get_cny_to_rub()
    return rate
