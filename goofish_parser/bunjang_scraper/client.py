import logging
import time
from typing import Any, Optional

import httpx

BUNJANG_SEARCH_URL = "https://api.bunjang.co.kr/api/1/find_v2.json"
logger = logging.getLogger(__name__)


async def search_bunjang(
    query: str,
    max_page: int = 10,
    per_page: int = 100,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
) -> list[dict]:
    all_items: list[dict] = []

    async with httpx.AsyncClient(
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://m.bunjang.co.kr/",
        },
        timeout=15,
    ) as client:
        for page in range(1, max_page + 1):
            params: dict[str, Any] = {
                "q": query,
                "page": page,
                "per": per_page,
                "order": "date",
                "stat": "used",
            }
            if price_min is not None:
                params["price_min"] = price_min
            if price_max is not None:
                params["price_max"] = price_max

            try:
                resp = await client.get(BUNJANG_SEARCH_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f"Bunjang search error (page {page}): {e}")
                break

            items = data.get("list", [])
            if not items:
                break

            if page == 1 and items:
                logger.debug(f"Bunjang first item keys: {list(items[0].keys())}")
                logger.debug(f"Bunjang first item first 500: {str(items[0])[:500]}")

            all_items.extend(items)
            time.sleep(0.5)

    return all_items
