import logging
import random
import time
from typing import Any, Optional

import httpx

from goofish_parser.services.user_agent import get_random_ua

BUNJANG_SEARCH_URL = "https://api.bunjang.co.kr/api/1/find_v2.json"
logger = logging.getLogger(__name__)


async def search_bunjang(
    query: str,
    max_page: int = 50,
    per_page: int = 100,
    max_items: int = 500,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
) -> list[dict]:
    all_items: list[dict] = []

    async with httpx.AsyncClient(
        headers={
            "User-Agent": get_random_ua(),
            "Accept": "application/json",
            "Referer": "https://m.bunjang.co.kr/",
        },
        timeout=15,
    ) as client:
        for page in range(1, max_page + 1):
            if len(all_items) >= max_items:
                break

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
            logger.debug(f"[bunjang] page={page} status={resp.status_code} items_count={len(items)} resp_len={len(resp.text)}")
            if not items:
                logger.info(f"[bunjang] No items on page {page}. Full response keys: {list(data.keys())}")
                logger.info(f"[bunjang] Response first 1000 chars: {resp.text[:1000]}")
                break

            if page == 1:
                logger.info(f"[bunjang] First item keys: {list(items[0].keys())}")
                logger.info(f"[bunjang] First item: {str(items[0])[:500]}")

            all_items.extend(items)
            time.sleep(0.5)

    return all_items[:max_items]
