import logging
from typing import Any, Optional

import httpx

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
    all_items: list[dict] = []

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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "x-requested-with": "XMLHttpRequest",
        "Referer": "https://www.carousell.sg/",
    }

    async with httpx.AsyncClient(headers=headers, timeout=15) as client:
        try:
            resp = await client.get(SEARCH_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"Carousell search error: {e}")
            return []

        products = data.get("data", {}).get("results", []) if isinstance(data, dict) else []
        if not products:
            products = data.get("products", [])

        for p in products:
            listing = p.get("listing", p)
            all_items.append(listing)

    return all_items
