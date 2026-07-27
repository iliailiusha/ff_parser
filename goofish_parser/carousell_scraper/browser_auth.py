import logging
import re
from typing import Any, Optional

from goofish_parser.config import CAROUSELL_EXTRA_HEADERS_JSON
from goofish_parser.carousell_scraper.cookie_manager import CarousellCookieManager

logger = logging.getLogger(__name__)
_cookie_manager = CarousellCookieManager()


SEARCH_GRAPHQL = """
query SearchTabs($query: String!, $count: Int!) {
    search(query: $query, count: $count, offset: 0) {
        listings {
            id
            title
            price {
                amount
                currency
            }
            images { url }
            location
            condition
            seller { id username }
            createdAt
            description
            slug
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

    api_items = await _search_via_api(query, count, domain, sort, price_min, price_max)
    if api_items:
        logger.info("Carousell API: %d items for query='%s'", len(api_items), query)
        return api_items

    html_items = await _search_via_html(query, domain, price_min, price_max)
    if html_items:
        logger.info("Carousell HTML: %d items for query='%s'", len(html_items), query)
        return html_items

    logger.info("Carousell: no results for query='%s'", query)
    return []


async def _search_via_api(
    query: str, count: int, domain: str, sort: int = 3,
    price_min: Optional[int] = None, price_max: Optional[int] = None,
) -> list[dict]:
    try:
        from curl_cffi.requests import AsyncSession
    except ImportError:
        logger.error("curl_cffi not installed")
        return []

    cookies = _cookie_manager.load()
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items()) if cookies else ""

    for impersonate in ("chrome124", "safari15_5"):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/124.0.0.0 Safari/537.36",
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

            async with AsyncSession() as session:
                resp = await session.post(
                    f"https://{domain}/api-service/graphql",
                    json=payload, headers=headers,
                    impersonate=impersonate, timeout=10,
                )

            if resp.status_code != 200:
                logger.debug("Carousell API %s: HTTP %d", impersonate, resp.status_code)
                continue

            set_cookie = resp.headers.get("set-cookie", "")
            if set_cookie and "cf_clearance" in set_cookie:
                for part in set_cookie.split(";"):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        cookies[k.strip()] = v.strip()
                _cookie_manager.save(cookies)
                cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())

            data = resp.json()
            listings = data.get("data", {}).get("search", {}).get("listings", [])
            if not listings:
                logger.debug("Carousell API %s: no listings", impersonate)
                continue

            logger.info("Carousell API %s: %d listings", impersonate, len(listings))
            items = _api_listings_to_items(listings, domain)
            return _apply_price_filter(items, price_min, price_max)

        except Exception as e:
            logger.debug("Carousell API %s error: %s", impersonate, e)

    return []


async def _search_via_html(
    query: str, domain: str,
    price_min: Optional[int] = None, price_max: Optional[int] = None,
) -> list[dict]:
    try:
        from curl_cffi.requests import AsyncSession
    except ImportError:
        return []

    url = f"https://{domain}/search/?q={query}&sort=time_created_desc"
    cookies = _cookie_manager.load()
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items()) if cookies else ""

    for impersonate in ("chrome124",):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            }
            if cookie_header:
                headers["Cookie"] = cookie_header

            async with AsyncSession() as session:
                resp = await session.get(url, headers=headers, impersonate=impersonate, timeout=10)

            if resp.status_code != 200:
                logger.debug("Carousell HTML %s: HTTP %d", impersonate, resp.status_code)
                continue

            text = resp.text
            items = _parse_html_listings(text, domain)
            if items:
                return _apply_price_filter(items, price_min, price_max)

        except Exception as e:
            logger.debug("Carousell HTML %s error: %s", impersonate, e)

    return []


def _parse_html_listings(html: str, domain: str) -> list[dict]:
    items = []
    pattern = re.compile(
        r'<a[^>]*href\s*=\s*["\']/p/([^"\'?#]+)[^>]*>.*?'
        r'<img[^>]*src\s*=\s*["\']([^"\']+)["\'][^>]*>.*?'
        r'<p[^>]*class\s*=\s*["\'][^"\']*title[^"\']*["\'][^>]*>(.*?)</p>.*?'
        r'<p[^>]*class\s*=\s*["\'][^"\']*price[^"\']*["\'][^>]*>(.*?)</p>',
        re.DOTALL,
    )
    seen = set()
    for slug, img, title, price_text in pattern.findall(html):
        item_id = slug.split("/")[0]
        if item_id in seen:
            continue
        seen.add(item_id)
        price = 0.0
        try:
            price = float(re.sub(r"[^0-9.]", "", price_text))
        except (ValueError, AttributeError):
            pass
        items.append({
            "id": item_id,
            "title": title.strip(),
            "price": price,
            "images": [img],
            "url": f"https://{domain}/p/{slug}",
            "location": "",
            "condition": "",
            "created_at": "",
            "description": "",
        })
    return items


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
            s = str(val).replace(",", "").replace("SGD", "").replace("$", "").replace("¥", "").strip()
            return float(s) if s else 0.0
        except (ValueError, AttributeError):
            return 0.0

    result = list(items)
    if price_min is not None:
        result = [i for i in result if _parse(i.get("price", 0)) >= price_min]
    if price_max is not None:
        result = [i for i in result if _parse(i.get("price", 0)) <= price_max]
    return result
