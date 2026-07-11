import json
import logging
import time
from typing import Any, Optional

from curl_cffi.requests import AsyncSession

logger = logging.getLogger(__name__)

SEARCH_API = "https://api.mercari.jp/v2/entities:search"
SEARCH_PAGE = "https://jp.mercari.com/search"


async def search_mercari_jp(
    query: str,
    limit: int = 50,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    sort: str = "created_time",
    order: str = "desc",
) -> list[dict]:
    all_items: list[dict] = []

    payload = {
        "pageSize": min(limit, 120),
        "searchCondition": {
            "keyword": query,
            "sort": sort,
            "order": order,
            "status": ["on_sale"],
        },
        "defaultSearchConditions": {
            "excludeKeyword": "",
        },
    }
    if price_min is not None:
        payload["searchCondition"]["priceMin"] = price_min
    if price_max is not None:
        payload["searchCondition"]["priceMax"] = price_max

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://jp.mercari.com",
        "Referer": "https://jp.mercari.com/",
        "X-Platform": "web",
    }

    async with AsyncSession() as session:
        page_token = None
        fetched = 0
        max_pages = 3

        for page in range(max_pages):
            if page_token:
                payload["pageToken"] = page_token
            else:
                payload.pop("pageToken", None)

            try:
                resp = await session.post(
                    SEARCH_API,
                    json=payload,
                    headers=headers,
                    impersonate="chrome124",
                    timeout=30,
                )
                if resp.status_code == 404:
                    logger.warning("Mercari JP API returned 404, falling back to HTML scrape")
                    return await _scrape_search_page(query, limit, session)

                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f"Mercari JP API search error: {e}, falling back to HTML scrape")
                return await _scrape_search_page(query, limit, session)

            items = data.get("items", [])
            if not items:
                break

            for item in items:
                all_items.append(item)
                fetched += 1

            page_token = data.get("meta", {}).get("nextPageToken")
            if not page_token or fetched >= limit:
                break

            time.sleep(0.5)

    if not all_items:
        async with AsyncSession() as session:
            return await _scrape_search_page(query, limit, session)

    return all_items


async def _scrape_search_page(query: str, limit: int, session: AsyncSession) -> list[dict]:
    try:
        params = {"keyword": query, "limit": min(limit, 120)}
        resp = await session.get(
            SEARCH_PAGE,
            params=params,
            headers={
                "Accept": "text/html",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            },
            impersonate="chrome124",
            timeout=30,
        )
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        logger.error(f"Mercari JP HTML scrape error: {e}")
        return []

    items = _extract_items_from_html(html)
    logger.info(f"Mercari JP HTML scrape found {len(items)} items")
    return items


def _extract_items_from_html(html: str) -> list[dict]:
    items = []

    import re

    patterns = [
        r'__NEXT_DATA__[^>]*type="application/json"[^>]*>(.*?)</script>',
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    ]

    for pattern in patterns:
        match = re.search(pattern, html, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                props = data.get("props", {}).get("pageProps", {})
                items_data = props.get("items", []) or props.get("searchResult", {}).get("items", [])
                if items_data:
                    return items_data
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

    import re

    item_blocks = re.findall(
        r'class="[^"]*item[^"]*"[^>]*>.*?data-testid="item-cell".*?<a[^>]*href="(/item/[^"]+)"[^>]*>.*?<img[^>]*src="([^"]+)".*?class="[^"]*name[^"]*"[^>]*>(.*?)</div>.*?class="[^"]*price[^"]*"[^>]*>.*?¥?([0-9,]+)',
        html, re.DOTALL
    )

    seen_ids = set()
    for match in item_blocks:
        item_url = match[0]
        item_id = item_url.split("/")[-1] if "/" in item_url else item_url
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)

        img_url = match[1]
        name = re.sub(r'<[^>]+>', '', match[2]).strip()
        price_str = match[3].replace(",", "")

        try:
            price = int(price_str)
        except ValueError:
            price = 0

        items.append({
            "id": item_id,
            "name": name,
            "price": price,
            "photos": [{"url": img_url}] if img_url else [],
            "item_url": f"https://jp.mercari.com{item_url}",
            "status": "on_sale",
        })

    return items
