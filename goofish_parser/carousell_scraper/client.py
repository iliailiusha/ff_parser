import json
import logging
from typing import Any, Optional

from curl_cffi.requests import AsyncSession

logger = logging.getLogger(__name__)

CAROUSELL_COUNTRIES = {
    "SG": {"currency": "SGD", "name": "Singapore"},
    "MY": {"currency": "MYR", "name": "Malaysia"},
    "PH": {"currency": "PHP", "name": "Philippines"},
    "ID": {"currency": "IDR", "name": "Indonesia"},
    "HK": {"currency": "HKD", "name": "Hong Kong"},
    "TW": {"currency": "TWD", "name": "Taiwan"},
}

DEFAULT_COUNTRY = "SG"

SEARCH_URL = "https://www.carousell.sg/api-service/search/search/1.5/"


async def search_carousell(
    query: str,
    count: int = 50,
    country: str = DEFAULT_COUNTRY,
    sort: int = 3,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
) -> list[dict]:
    params: dict[str, Any] = {
        "query": query,
        "count": count,
        "country_code": country,
        "sort": sort,
        "includeSuggestions": "false",
    }
    if price_min is not None:
        params["price_min"] = price_min
    if price_max is not None:
        params["price_max"] = price_max

    headers = {
        "Accept": "application/json",
        "x-requested-with": "XMLHttpRequest",
        "Referer": "https://www.carousell.sg/",
    }

    async with AsyncSession() as session:
        try:
            resp = await session.get(
                SEARCH_URL,
                params=params,
                headers=headers,
                impersonate="chrome124",
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"Carousell search error: {e}")
            return []

        products = data.get("data", {}).get("results", []) if isinstance(data, dict) else []
        if not products:
            products = data.get("products", [])

        all_items = []
        for p in products:
            listing = p.get("listing", p)
            all_items.append(listing)

        return all_items
