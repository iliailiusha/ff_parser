import logging
import random
import re
import time
from typing import Any, Optional

import httpx

from goofish_parser.services.user_agent import get_random_ua

BUNJANG_SEARCH_URL = "https://api.bunjang.co.kr/api/1/find_v2.json"
BUNJANG_KOREAN_URL = "https://api.bunjang.co.kr/api/1/find_v2.json"
logger = logging.getLogger(__name__)

# Simple brand/model translations for Bunjang fallback (longer matches first!)
_BUNJANG_KO: list[tuple[str, str]] = [
    ("raf simons", "라프 시몬스"),
    ("adidas", "아디다스"),
    ("nike", "나이키"),
    ("sneakers", "운동화"),
    ("sneaker", "운동화"),
    ("raf", "라프"),
    ("simons", "시몬스"),
]


def _translate_to_korean(text: str) -> str:
    """Translate English brand/model words to Korean for Bunjang search."""
    result = text.lower()
    for eng, kor in _BUNJANG_KO:
        if eng in result:
            result = result.replace(eng, kor)
    return result


async def search_bunjang(
    query: str,
    max_page: int = 50,
    per_page: int = 100,
    max_items: int = 500,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    retry_with_korean: bool = True,
) -> list[dict]:
    all_items: list[dict] = []
    query = re.sub(r"\s+", " ", query.strip())
    no_price_retry_done = False
    no_stat_retry_done = False

    while True:
        retry_just_triggered = False
        retry_stat_triggered = False
        headers = {
            "User-Agent": get_random_ua(),
            "Accept": "application/json",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            "Referer": "https://m.bunjang.co.kr/",
        }
        async with httpx.AsyncClient(headers=headers, timeout=15) as client:
            for attempt, current_query in _get_search_queries(query, retry_with_korean):
                if all_items:
                    break

                logger.debug(f"[bunjang] Search attempt {attempt}: query='{current_query}'")
                for page in range(1, max_page + 1):
                    if len(all_items) >= max_items:
                        break

                    params: dict[str, Any] = {
                        "q": current_query,
                        "page": page,
                        "per": per_page,
                        "order": "date",
                    }
                    if not no_stat_retry_done:
                        params["stat"] = "used"
                    if not no_price_retry_done:
                        if price_min is not None:
                            params["price_min"] = price_min
                        if price_max is not None:
                            params["price_max"] = price_max

                    try:
                        resp = await client.get(BUNJANG_SEARCH_URL, params=params)
                        resp.raise_for_status()
                        data = resp.json()
                    except Exception as e:
                        logger.error(f"Bunjang search error (page {page}, query='{current_query}'): {e}")
                        break

                    raw_text = resp.text
                    items = data.get("list", [])
                    if not items and isinstance(data.get("data"), dict):
                        items = data["data"].get("list", [])
                    num_found = data.get("num_found", 0) or (data.get("data") or {}).get("num_found", 0)
                    no_result = data.get("no_result", False)
                    logger.debug(
                        f"[bunjang] page={page} query='{current_query}' "
                        f"status={resp.status_code} items_count={len(items)} "
                        f"num_found={num_found} no_result={no_result} resp_len={len(raw_text)}"
                    )

                    if not items:
                        logger.debug(
                            f"[bunjang] Raw response (first 500): {raw_text[:500]}"
                        )
                        # If no_result and price filter active, retry without price
                        if page == 1 and no_result and not no_price_retry_done and (price_min is not None or price_max is not None):
                            logger.info(
                                f"[bunjang] no_result=true with price filter, retrying without price"
                            )
                            no_price_retry_done = True
                            retry_just_triggered = True
                            break  # break page loop, will restart from outer while
                        # If no_result without price filter, try removing stat=used
                        if page == 1 and no_result and not no_stat_retry_done:
                            logger.info(
                                f"[bunjang] no_result=true without price, retrying without stat=used"
                            )
                            no_stat_retry_done = True
                            retry_stat_triggered = True
                            break
                        # If page 1 has no items but num_found > 0, could be pagination issue
                        if page == 1 and num_found and int(num_found) > 0:
                            logger.info(
                                f"[bunjang] Page 1 empty but num_found={num_found} for query='{current_query}'. "
                                f"Trying page 2..."
                            )
                            continue  # Skip to page 2
                        logger.debug(
                            f"[bunjang] No items on page {page} for query='{current_query}'"
                        )
                        break  # No more items for this query

                    if page == 1:
                        logger.info(f"[bunjang] First item keys: {list(items[0].keys())}")
                        logger.info(f"[bunjang] First item: {str(items[0])[:500]}")

                    all_items.extend(items)
                    time.sleep(0.5)

                # Break query loop to restart from outer while
                if (retry_just_triggered or retry_stat_triggered) and not all_items:
                    break

        # Restart without price filter if needed
        if no_price_retry_done and not all_items and (price_min is not None or price_max is not None):
            price_min = None
            price_max = None
            continue
        # If stat=used retry was done and still no items, continue with next query variant
        if retry_stat_triggered:
            continue
        break

    return all_items[:max_items]


def _get_search_queries(query: str, retry_with_korean: bool = True):
    """Yield (attempt_num, query_string) tuples for search attempts."""
    yield (1, query)
    if retry_with_korean:
        korean_query = _translate_to_korean(query)
        if korean_query.lower() != query.lower():
            yield (2, korean_query)
