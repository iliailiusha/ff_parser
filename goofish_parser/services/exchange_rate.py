import asyncio
import logging
from datetime import date
from typing import Optional

from goofish_parser.storage.db import get_rate_cache, set_rate_cache
from goofish_parser.config import KRW_TO_RUB_FALLBACK, SGD_TO_RUB_FALLBACK, JPY_TO_RUB_FALLBACK, CNY_TO_RUB_FALLBACK

CBR_URL = "https://www.cbr-xml-daily.ru/daily_json.js"
logger = logging.getLogger(__name__)

_shared_client = None
_client_lock = asyncio.Lock()

async def _get_client():
    global _shared_client
    if _shared_client is None:
        async with _client_lock:
            if _shared_client is None:
                import httpx
                _shared_client = httpx.AsyncClient(timeout=10.0)
    return _shared_client


async def _fetch_currency_rate(code: str) -> Optional[float]:
    try:
        client = await _get_client()
        resp = await client.get(CBR_URL)
        resp.raise_for_status()
        data = resp.json()
        val = data["Valute"][code]
        value = val["Value"]
        nominal = val["Nominal"]
        rate = value / nominal
        logger.info(f"{code} rate from CBR: {rate:.4f} RUB (nominal={nominal}, value={value})")
        return round(rate, 4)
    except Exception as e:
        logger.warning(f"Failed to fetch {code} rate from CBR: {e}")
        return None


async def _get_rate_to_rub(code: str, fallback: float) -> float:
    today = date.today().isoformat()
    cache_key = f"{code}_TO_RUB"
    cached = get_rate_cache(cache_key)
    if cached:
        cached_date, rate = cached
        if cached_date == today:
            return rate

    rate = await _fetch_currency_rate(code)
    if rate is not None:
        set_rate_cache(cache_key, rate)
        return rate

    if cached:
        _, rate = cached
        logger.info(f"Using stale cached {code} rate: {rate}")
        return rate

    logger.info(f"Using fallback {code} rate: {fallback}")
    return fallback


async def fetch_krw_rate() -> Optional[float]:
    return await _fetch_currency_rate("KRW")


async def get_krw_to_rub() -> float:
    return await _get_rate_to_rub("KRW", KRW_TO_RUB_FALLBACK)


async def get_sgd_to_rub() -> float:
    return await _get_rate_to_rub("SGD", 60.0)


async def get_jpy_to_rub() -> float:
    return await _get_rate_to_rub("JPY", 0.55)


async def get_cny_to_rub() -> float:
    return await _get_rate_to_rub("CNY", CNY_TO_RUB_FALLBACK)


async def get_rate_to_rub(currency: str) -> float:
    if currency in ("₩", "KRW"):
        return await get_krw_to_rub()
    if currency in ("SGD", "SGD$"):
        return await get_sgd_to_rub()
    if currency in ("¥", "JPY"):
        return await get_jpy_to_rub()
    if currency == "CNY":
        return await get_cny_to_rub()
    return await get_krw_to_rub()


async def update_rate_daily() -> float:
    rate = await fetch_krw_rate()
    if rate is None:
        rate = await get_krw_to_rub()
    return rate
