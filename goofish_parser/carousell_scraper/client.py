import logging
import time
from typing import Any, Optional

import httpx

CAROUSELL_SEARCH_URL = "https://www.carousell.com/api-service/search/search/1.0/search"
logger = logging.getLogger(__name__)


async def search_carousell(
    query: str,
    limit: int = 50,
    count: int = 5,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
) -> list[dict]:
    all_items: list[dict] = []
    offset = 0

    async with httpx.AsyncClient(
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Origin": "https://www.carousell.com",
            "Referer": "https://www.carousell.com/search/",
        },
        timeout=15,
    ) as client:
        for page in range(count):
            params: dict[str, Any] = {
                "query": query,
                "count": limit,
                "start": offset,
                "countryCode": "SG",
                "locale": "en",
                "searchType": "all",
                "includeSuggestions": "false",
            }
            if price_min is not None:
                params["minPrice"] = price_min
            if price_max is not None:
                params["maxPrice"] = price_max

            try:
                resp = await client.get(CAROUSELL_SEARCH_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f"Carousell search error (page {page}): {e}")
                break

            data_result = data.get("data", {}) if isinstance(data, dict) else {}
            results = data_result.get("results", [])
            items = []
            for r in results:
                listing = r.get("listing", r) if isinstance(r, dict) else r
                if isinstance(listing, dict):
                    items.append(listing)
            if not items:
                break

            all_items.extend(items)
            offset += limit
            time.sleep(0.5)

    return all_items
