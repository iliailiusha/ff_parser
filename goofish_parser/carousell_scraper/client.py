import json
import logging
import re
from typing import Any, Optional

import json as json_mod

from curl_cffi.requests import AsyncSession

from goofish_parser.carousell_scraper.cookie_manager import CarousellCookieManager
from goofish_parser.services.user_agent import get_random_ua

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

CAROUSELL_DOMAINS = {
    "SG": "www.carousell.sg",
    "MY": "www.carousell.com.my",
    "PH": "www.carousell.ph",
    "ID": "www.carousell.co.id",
    "HK": "www.carousell.com.hk",
    "TW": "www.carousell.com.tw",
}

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL)

_cookie_mgr = CarousellCookieManager()


def _parse_next_data(html: str) -> Optional[dict]:
    m = _NEXT_DATA_RE.search(html)
    if not m:
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
            item_id = ent.get("id") or ent.get("listingId") or ent.get("cardId") or ""
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


def _make_headers(domain: str) -> dict[str, str]:
    ua = get_random_ua()
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://{domain}/",
        "Origin": f"https://{domain}",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
    }


def _build_params(
    query: str,
    sort: int = 3,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
) -> dict[str, str]:
    params: dict[str, str] = {"q": query}
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
    return params


async def _try_curl_cffi(
    search_url: str,
    params: dict[str, str],
    headers: dict[str, str],
    cookies: dict[str, str],
) -> Optional[str]:
    try:
        async with AsyncSession() as session:
            resp = await session.get(
                search_url,
                params=params,
                headers=headers,
                cookies=cookies,
                impersonate="chrome124",
                timeout=30,
            )
        if resp.status_code == 403 or "Just a moment" in resp.text:
            logger.warning("Carousell curl_cffi blocked by Cloudflare")
            return None
        return resp.text
    except Exception as e:
        logger.error(f"Carousell curl_cffi error: {e}")
        return None


async def _fetch_via_browser(search_url: str, params: dict[str, str]) -> tuple[Optional[str], dict[str, str]]:
    from goofish_parser.carousell_scraper.browser_auth import CarousellBrowserAuth

    qs = "&".join(f"{k}={v}" for k, v in params.items())
    full_url = f"{search_url}?{qs}"
    logger.info("Carousell browser auth: %s", full_url)

    auth = CarousellBrowserAuth()
    try:
        cookies, html = await auth.get_cookies_and_html(full_url, timeout=90)
        _cookie_mgr.save(cookies)
        return html, cookies
    except Exception as e:
        logger.error(f"Carousell browser auth failed: {e}")
        return None, {}


async def search_carousell(
    query: str,
    count: int = 50,
    country: str = DEFAULT_COUNTRY,
    sort: int = 3,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
) -> list[dict]:
    domain = CAROUSELL_DOMAINS.get(country, CAROUSELL_DOMAINS[DEFAULT_COUNTRY])
    headers = _make_headers(domain)
    params = _build_params(query, sort, price_min, price_max)
    search_url = f"https://{domain}/search/"

    logger.info(f"Carousell search: {search_url} params={params}")

    cookies = _cookie_mgr.load()
    html = None

    if _cookie_mgr.is_valid(cookies):
        logger.info("Carousell: trying curl_cffi with saved cookies")
        html = await _try_curl_cffi(search_url, params, headers, cookies)

    if not html:
        logger.info("Carousell: fetching via Playwright browser")
        html, cookies = await _fetch_via_browser(search_url, params)

    if not html:
        logger.info("Carousell: trying GraphQL API fallback")
        items = await _search_via_api(query, count, domain, sort, price_min, price_max)
        return items

    next_data = _parse_next_data(html)
    if next_data:
        items = _extract_items_from_next_data(next_data)
        items = _apply_price_filter(items, price_min, price_max)
        items = items[:count]
        logger.info(f"Carousell: found {len(items)} items for query='{query}'")
        return items

    logger.warning("Carousell: no __NEXT_DATA__ in response, trying API fallback")
    items = await _search_via_api(query, count, domain, sort, price_min, price_max)
    return items


def _parse_price_val(val: Any) -> float:
    try:
        s = str(val).replace(",", "").replace("SGD", "").replace("$", "").replace("¥", "").strip()
        return float(s) if s else 0.0
    except (ValueError, AttributeError):
        return 0.0


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
            images {
                url
            }
            location
            condition
            seller {
                id
                username
            }
            createdAt
            description
            slug
        }
    }
}
"""


async def _search_via_api(
    query: str,
    count: int,
    domain: str,
    sort: int = 3,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
) -> list[dict]:
    for impersonate in ("chrome124", "firefox110", "safari15_5"):
        try:
            ua = get_random_ua()
            api_headers = {
                "User-Agent": ua,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Referer": f"https://{domain}/",
                "Origin": f"https://{domain}",
                "x-requested-with": "XMLHttpRequest",
            }

            payload = {
                "operationName": "SearchTabs",
                "query": SEARCH_GRAPHQL,
                "variables": {"query": query, "count": min(count, 100)},
            }

            api_url = f"https://{domain}/api-service/graphql"
            async with AsyncSession() as session:
                resp = await session.post(
                    api_url,
                    json=payload,
                    headers=api_headers,
                    impersonate=impersonate,
                    timeout=20,
                )

            if resp.status_code != 200:
                logger.debug("Carousell API %s: HTTP %d", impersonate, resp.status_code)
                continue

            data = resp.json()
            listings = (
                data.get("data", {})
                .get("search", {})
                .get("listings", [])
            )

            if not listings:
                logger.debug("Carousell API %s: no listings in response", impersonate)
                continue

            logger.info("Carousell API %s: found %d listings", impersonate, len(listings))
            return _api_listings_to_items(listings, domain)

        except Exception as e:
            logger.debug("Carousell API %s error: %s", impersonate, e)

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

        location = str(ent.get("location", "") or "")
        condition = str(ent.get("condition", "") or "")
        seller = ent.get("seller", {}) or {}
        seller_id = str(seller.get("id", "") if isinstance(seller, dict) else "")
        created_at = str(ent.get("createdAt", "") or "")
        description = str(ent.get("description", "") or "")
        slug = ent.get("slug", "") or item_id

        item = {
            "id": item_id,
            "title": title,
            "price": price_raw,
            "images": images,
            "seller": seller,
            "location": location,
            "condition": condition,
            "created_at": created_at,
            "url": f"https://{domain}/p/{slug}",
            "description": description,
            "seller_id": seller_id,
        }
        items.append(item)

    return items


def _apply_price_filter(
    items: list[dict],
    price_min: Optional[int],
    price_max: Optional[int],
) -> list[dict]:
    result = list(items)
    if price_min is not None:
        result = [i for i in result if _parse_price_val(i.get("price", 0)) >= price_min]
    if price_max is not None:
        result = [i for i in result if _parse_price_val(i.get("price", 0)) <= price_max]
    return result
