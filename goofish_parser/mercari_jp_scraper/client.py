import json
import logging
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

SEARCH_API = "https://jp.mercari.com/api/v1/search"

MERCARI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ja,en;q=0.9",
    "Origin": "https://jp.mercari.com",
    "Referer": "https://jp.mercari.com/",
    "x-requested-with": "XMLHttpRequest",
}


async def search_mercari_jp(
    query: str,
    limit: int = 50,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    sort: str = "created_time",
    order: str = "desc",
) -> list[dict]:
    all_items: list[dict] = []

    params: dict[str, Any] = {
        "keyword": query,
        "limit": min(limit, 120),
        "sort": sort,
        "order": order,
        "status": "on_sale",
    }
    if price_min is not None:
        params["price_min"] = price_min
    if price_max is not None:
        params["price_max"] = price_max

    async with httpx.AsyncClient(headers=MERCARI_HEADERS, timeout=15) as client:
        page_token = None
        fetched = 0
        max_pages = 3

        for page in range(max_pages):
            if page_token:
                params["page_token"] = page_token
            else:
                params.pop("page_token", None)

            try:
                resp = await client.get(SEARCH_API, params=params)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f"Mercari JP search error (page {page}): {e}")
                break

            items = data.get("items", []) or data.get("data", [])
            if not items:
                break

            for item in items:
                all_items.append(item)
                fetched += 1

            page_token = data.get("next_page_token")
            if not page_token or fetched >= limit:
                break

            time.sleep(0.5)

    return all_items
