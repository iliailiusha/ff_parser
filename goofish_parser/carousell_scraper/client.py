import json
import logging
import re
from typing import Any, Optional
from urllib.parse import quote

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


async def search_carousell(
    query: str,
    count: int = 50,
    country: str = DEFAULT_COUNTRY,
    sort: int = 3,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
) -> list[dict]:
    search_url = f"https://www.carousell.sg/search/{quote(query)}"

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-SG,en;q=0.9,zh-SG;q=0.8,zh;q=0.7,en-GB;q=0.6,en-US;q=0.5",
        "Referer": "https://www.carousell.sg/",
    }

    async with AsyncSession() as session:
        try:
            resp = await session.get(
                "https://www.carousell.sg/",
                headers=headers,
                impersonate="chrome124",
                timeout=30,
            )
        except Exception as e:
            logger.warning(f"Carousell homepage request failed: {e}")

        try:
            resp = await session.get(
                search_url,
                headers=headers,
                impersonate="chrome124",
                timeout=30,
            )
            resp.raise_for_status()
            html = resp.text
        except Exception as e:
            logger.error(f"Carousell search page error: {e}")
            return []

        items = _extract_from_html(html)
        logger.info(f"Carousell HTML scrape found {len(items)} items")
        return items


def _extract_from_html(html: str) -> list[dict]:
    items = []

    embedded = _find_json_data(html)
    if embedded:
        logger.info("Carousell: found embedded JSON data")
        return embedded

    card_pattern = re.compile(
        r'data-testid=["\']listing-card["\'][^>]*>.*?'
        r'<a[^>]*href=["\'](/p/[^"\']+)["\'][^>]*>.*?'
        r'<img[^>]*src=["\']([^"\']+)["\'][^>]*>.*?'
        r'<p[^>]*title=["\']([^"\']+)["\'][^>]*>.*?'
        r'人民币|S\$?\s*([0-9,]+)',
        re.DOTALL,
    )

    for match in card_pattern.finditer(html):
        item_url = match.group(1)
        img_url = match.group(2)
        title = match.group(3)
        price_str = match.group(4).replace(",", "") if match.group(4) else "0"

        item_id = item_url.split("/")[-1] if "/" in item_url else item_url
        try:
            price = int(price_str)
        except ValueError:
            price = 0

        items.append({
            "id": item_id,
            "title": title,
            "name": title,
            "price": price,
            "images": [{"url": img_url}] if img_url else [],
            "item_url": f"https://www.carousell.sg{item_url}",
            "url": f"https://www.carousell.sg{item_url}",
        })

    return items


def _find_json_data(html: str) -> list[dict]:
    patterns = [
        r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        r'<script[^>]*id="__NEXT_DATA__"[^>]*type="application/json"[^>]*>(.*?)</script>',
        r'window\.__INITIAL_STATE__\s*=\s*({.*?});',
    ]

    for pattern in patterns:
        match = re.search(pattern, html, re.DOTALL)
        if not match:
            continue
        try:
            data = json.loads(match.group(1))
        except (json.JSONDecodeError, IndexError):
            continue

        listings = _traverse_for_listings(data)
        if listings:
            return listings

    return []


def _traverse_for_listings(data: Any, depth: int = 0) -> Optional[list[dict]]:
    if depth > 5:
        return None
    if isinstance(data, dict):
        if "listings" in data and isinstance(data["listings"], list):
            return [l.get("listing", l) for l in data["listings"]]
        if "results" in data and isinstance(data["results"], list):
            return data["results"]
        for v in data.values():
            result = _traverse_for_listings(v, depth + 1)
            if result:
                return result
    elif isinstance(data, list):
        for v in data:
            result = _traverse_for_listings(v, depth + 1)
            if result:
                return result
    return None
