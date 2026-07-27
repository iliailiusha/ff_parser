import logging
from typing import Any, Optional

from goofish_parser.carousell_scraper.cookie_manager import CarousellCookieManager

logger = logging.getLogger(__name__)
_cookie_manager = CarousellCookieManager()


SEARCH_GRAPHQL = """
query SearchTabs($query: String!, $count: Int!) {
    search(query: $query, count: $count, offset: 0) {
        listings {
            id title
            price { amount currency }
            images { url }
            location condition
            seller { id username }
            createdAt description slug
        }
    }
}
"""


async def search_carousell_pw(
    query: str,
    count: int = 50,
    country: str = "SG",
    sort: int = 3,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
) -> list[dict]:
    domains = {
        "SG": "www.carousell.sg", "MY": "www.carousell.com.my",
        "PH": "www.carousell.ph", "ID": "www.carousell.co.id",
        "HK": "www.carousell.com.hk", "TW": "www.carousell.com.tw",
    }
    domain = domains.get(country, domains["SG"])

    try:
        from curl_cffi.requests import AsyncSession
    except ImportError:
        logger.error("curl_cffi not installed")
        return []

    cookies = _cookie_manager.load()
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items()) if cookies else ""
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

    headers = {
        "User-Agent": ua,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Referer": f"https://{domain}/",
        "Origin": f"https://{domain}",
        "x-requested-with": "XMLHttpRequest",
    }
    if cookie_header:
        headers["Cookie"] = cookie_header

    payload = {
        "operationName": "SearchTabs",
        "query": SEARCH_GRAPHQL,
        "variables": {"query": query, "count": min(count, 100)},
    }

    try:
        async with AsyncSession() as session:
            resp = await session.post(
                f"https://{domain}/api-service/graphql",
                json=payload, headers=headers,
                impersonate="chrome124", timeout=10,
            )

        if resp.status_code != 200:
            logger.debug("Carousell API: HTTP %d", resp.status_code)
            return []

        set_cookie = resp.headers.get("set-cookie", "")
        if set_cookie and "cf_clearance" in set_cookie:
            for part in set_cookie.split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    cookies[k.strip()] = v.strip()
            _cookie_manager.save(cookies)

        data = resp.json()
        listings = data.get("data", {}).get("search", {}).get("listings", [])

        if not listings:
            logger.debug("Carousell API: no listings")
            return []

        items = _api_listings_to_items(listings, domain)
        return _apply_price_filter(items, price_min, price_max)

    except Exception as e:
        logger.debug("Carousell API error: %s", e)
        return []


def _api_listings_to_items(listings: list[dict], domain: str) -> list[dict]:
    items = []
    for ent in listings:
        if not isinstance(ent, dict):
            continue
        item_id = str(ent.get("id", ""))
        title = str(ent.get("title", ""))
        if not item_id or not title:
            continue

        price_raw = ent.get("price", {})
        if isinstance(price_raw, dict):
            price_raw = price_raw.get("amount", "0")

        images_raw = ent.get("images", []) or []
        images = []
        for img in images_raw:
            if isinstance(img, dict):
                u = img.get("url", "")
                if u:
                    images.append(u)
            elif isinstance(img, str):
                images.append(img)

        seller = ent.get("seller", {}) or {}
        slug = ent.get("slug", "") or item_id

        items.append({
            "id": item_id,
            "title": title,
            "price": price_raw,
            "images": images,
            "seller": seller,
            "location": str(ent.get("location", "") or ""),
            "condition": str(ent.get("condition", "") or ""),
            "created_at": str(ent.get("createdAt", "") or ""),
            "url": f"https://{domain}/p/{slug}",
            "description": str(ent.get("description", "") or ""),
            "seller_id": str(seller.get("id", "") if isinstance(seller, dict) else ""),
        })
    return items


def _apply_price_filter(
    items: list[dict], price_min: Optional[int], price_max: Optional[int],
) -> list[dict]:
    def _parse(val: Any) -> float:
        try:
            s = str(val).replace(",", "").replace("SGD", "").replace("$", "").strip()
            return float(s) if s else 0.0
        except (ValueError, AttributeError):
            return 0.0

    result = list(items)
    if price_min is not None:
        result = [i for i in result if _parse(i.get("price", 0)) >= price_min]
    if price_max is not None:
        result = [i for i in result if _parse(i.get("price", 0)) <= price_max]
    return result
