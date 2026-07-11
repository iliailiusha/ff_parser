import json
import logging
import re
from typing import Any, Optional
from urllib.parse import quote

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


async def search_carousell(
    query: str,
    count: int = 50,
    country: str = DEFAULT_COUNTRY,
    sort: int = 3,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
) -> list[dict]:
    items = await _try_curl_cffi(query)
    if items:
        return items

    items = await _try_httpx(query)
    if items:
        return items

    logger.warning("Carousell: all fetch methods failed, returning empty")
    return []


async def _try_curl_cffi(query: str) -> Optional[list[dict]]:
    try:
        from curl_cffi.requests import AsyncSession

        search_url = f"https://www.carousell.sg/search/{quote(query)}"
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-SG,en;q=0.9",
            "Referer": "https://www.carousell.sg/",
        }

        async with AsyncSession() as session:
            await session.get(
                "https://www.carousell.sg/",
                headers=headers,
                impersonate="chrome124",
                timeout=15,
            )

            resp = await session.get(
                search_url,
                headers=headers,
                impersonate="chrome124",
                timeout=20,
            )
            if resp.status_code != 200:
                logger.warning(f"Carousell curl_cffi returned {resp.status_code}")
                return None

            html = resp.text
            items = _extract_from_html(html)
            if items:
                logger.info(f"Carousell curl_cffi: {len(items)} items")
                return items
    except Exception as e:
        logger.warning(f"Carousell curl_cffi failed: {e}")

    return None


async def _try_httpx(query: str) -> Optional[list[dict]]:
    search_url = f"https://www.carousell.sg/search/{quote(query)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-SG,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.carousell.sg/",
        "Sec-Ch-Ua": '"Not/A)Brand";v="99", "Google Chrome";v="125", "Chromium";v="125"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            await client.get("https://www.carousell.sg/", headers=headers)
            resp = await client.get(search_url, headers=headers)
            if resp.status_code != 200:
                logger.warning(f"Carousell httpx returned {resp.status_code}")
                return None

            html = resp.text
            items = _extract_from_html(html)
            if items:
                logger.info(f"Carousell httpx: {len(items)} items")
                return items
    except Exception as e:
        logger.warning(f"Carousell httpx failed: {e}")

    return None


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
        r'[S$]\s*([0-9,]+)',
        re.DOTALL,
    )

    for match in card_pattern.finditer(html):
        item_url = match.group(1)
        img_url = match.group(2)
        title = match.group(3)
        price_str = match.group(4).replace(",", "")

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
