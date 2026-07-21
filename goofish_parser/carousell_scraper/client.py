import json
import logging
import re
import random
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

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

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
]

CAROUSELL_DOMAINS = {
    "SG": "www.carousell.sg",
    "MY": "www.carousell.com.my",
    "PH": "www.carousell.ph",
    "ID": "www.carousell.co.id",
    "HK": "www.carousell.com.hk",
    "TW": "www.carousell.com.tw",
}

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL)


def _parse_next_data(html: str) -> Optional[dict]:
    m = _NEXT_DATA_RE.search(html)
    if not m:
        logger.warning("__NEXT_DATA__ not found in Carousell page")
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse __NEXT_DATA__ JSON: {e}")
        return None


def _extract_items_from_next_data(data: dict) -> list[dict]:
    items: list[dict] = []
    try:
        search_results = (
            data.get("props", {})
            .get("pageProps", {})
            .get("searchResults", {})
        )
        if not search_results:
            search_results = (
                data.get("props", {})
                .get("pageProps", {})
                .get("listing", {})
            )

        entities = (
            search_results.get("entities", [])
            or search_results.get("listings", [])
            or search_results.get("items", [])
        )
        if not entities:
            results_arr = search_results.get("results", [])
            if results_arr and isinstance(results_arr, list):
                for r in results_arr:
                    if isinstance(r, dict):
                        e = r.get("entity", r.get("listing", r))
                        if isinstance(e, dict):
                            entities.append(e)

        if not entities:
            page_data = data.get("props", {}).get("pageProps", {})
            for key in ("listings", "results", "items", "cards", "products"):
                val = page_data.get(key, [])
                if val and isinstance(val, list):
                    entities = val
                    break

        for ent in entities:
            if not isinstance(ent, dict):
                continue
            item_id = ent.get("id") or ""
            if not item_id:
                item_id = ent.get("listingId") or ent.get("cardId") or ""

            if not item_id:
                continue

            title = (
                ent.get("title")
                or ent.get("name")
                or (ent.get("card") or {}).get("title")
                or ""
            )
            if not title:
                continue

            price_raw = (
                ent.get("price")
                or ent.get("priceInfo", {}).get("price")
                or (ent.get("card") or {}).get("price")
                or "0"
            )
            if isinstance(price_raw, dict):
                price_raw = price_raw.get("amount", "0")

            images = (
                ent.get("images", [])
                or ent.get("imageUrls", [])
                or ent.get("thumbnailUrls", [])
                or []
            )
            images_clean = []
            for img in images:
                if isinstance(img, dict):
                    u = img.get("url") or img.get("imageUrl") or ""
                    if u:
                        images_clean.append(u)
                elif isinstance(img, str):
                    images_clean.append(img)

            location = (
                ent.get("location")
                or ent.get("region")
                or ent.get("country")
                or ""
            )
            condition = (
                ent.get("condition")
                or ent.get("itemCondition")
                or ""
            )
            seller = ent.get("seller", {}) or {}
            if not isinstance(seller, dict):
                seller = {}
            seller_id = str(seller.get("id") or seller.get("username") or "")
            created_at = str(
                ent.get("createdAt")
                or ent.get("created")
                or ent.get("listingTime")
                or ""
            )
            description = ent.get("description") or ent.get("desc") or ""

            url = (
                ent.get("url")
                or ent.get("canonicalUrl")
                or ent.get("shareUrl")
                or ""
            )
            if not url:
                slug = ent.get("slug") or item_id
                url = f"https://www.carousell.sg/p/{slug}"

            item = {
                "id": item_id,
                "title": title,
                "price": price_raw,
                "images": images_clean,
                "seller": seller,
                "location": location,
                "condition": condition,
                "created_at": created_at,
                "url": url,
                "description": description,
                "seller_id": seller_id,
            }
            items.append(item)

    except Exception as e:
        logger.exception(f"Error extracting items from __NEXT_DATA__: {e}")

    return items


async def search_carousell(
    query: str,
    count: int = 50,
    country: str = DEFAULT_COUNTRY,
    sort: int = 3,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
) -> list[dict]:
    domain = CAROUSELL_DOMAINS.get(country, CAROUSELL_DOMAINS[DEFAULT_COUNTRY])
    ua = random.choice(USER_AGENTS)

    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": f"https://{domain}/",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
    }

    params = {"q": query}

    if price_min is not None:
        params["sp"] = str(price_min)
    if price_max is not None:
        params["ep"] = str(price_max)

    if sort == 1:
        params["sort"] = "price_asc"
    elif sort == 2:
        params["sort"] = "price_desc"
    elif sort == 3:
        params["sort"] = "time_created_desc"

    url = f"https://{domain}/search/"
    logger.info(f"Carousell search: {url} params={params}")

    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=30) as client:
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            html = resp.text
        except httpx.HTTPStatusError as e:
            logger.error(f"Carousell HTTP {e.response.status_code}: {e.response.text[:300]}")
            return []
        except Exception as e:
            logger.error(f"Carousell request error: {e}")
            return []

    next_data = _parse_next_data(html)
    if not next_data:
        # Try soup-based parsing as fallback
        return await _search_via_soup(html, domain)

    items = _extract_items_from_next_data(next_data)

    if not items:
        bs = BeautifulSoup(html, "lxml")
        cards = bs.select('[data-testid^="listing-card"], [class*="listing"], [class*="card"]')
        if cards:
            logger.info(f"Carousell: found {len(cards)} listing elements via soup, trying __NEXT_DATA__ extraction again")
            items = _extract_items_from_next_data(next_data)

    # Filter by price if set (server-side may not have applied it)
    if price_min is not None:
        items = [i for i in items if _parse_price_val(i.get("price", 0)) >= price_min]
    if price_max is not None:
        items = [i for i in items if _parse_price_val(i.get("price", 0)) <= price_max]

    items = items[:count]
    logger.info(f"Carousell: found {len(items)} items for query='{query}'")
    return items


def _parse_price_val(val: Any) -> float:
    try:
        s = str(val).replace(",", "").replace("SGD", "").replace("$", "").replace("¥", "").strip()
        return float(s) if s else 0.0
    except (ValueError, AttributeError):
        return 0.0


async def _search_via_soup(html: str, domain: str) -> list[dict]:
    logger.info("Carousell: trying soup-based fallback parsing")
    return []
