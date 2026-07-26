import asyncio
import json
import logging
import random
import re
import uuid
from base64 import urlsafe_b64encode
from time import time as now
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from goofish_parser.mercari_jp_scraper.rsc_parser import parse_rsc_items
from goofish_parser.services.user_agent import get_random_ua

logger = logging.getLogger(__name__)

SEARCH_URL_V2 = "https://api.mercari.jp/v2/entities:search"
SEARCH_URL_V3 = "https://api.mercari.jp/v3/entities:search"
SEARCH_PAGE_URL = "https://jp.mercari.com/search"

MERCARI_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

EXTRACT_ITEMS_JS = """
() => {
    const items = [];
    const cards = document.querySelectorAll('a[href*="/item/m"]');

    const seen = new Set();

    cards.forEach(link => {
        const href = link.getAttribute('href') || '';
        const match = href.match(/\\/item\\/(m\\d+)/);
        if (!match) return;
        const id = match[1];
        if (seen.has(id)) return;
        seen.add(id);

        const card = link.closest('div[class]') || link;
        const titleEl = link.querySelector('[class*="name"], [class*="title"], img[alt]');
        const priceEl = link.querySelector('[class*="price"], [class*="-x"]');
        const imageEl = link.querySelector('img[src]');
        const brandEl = document.querySelector('[class*="brand"]');

        const title = titleEl
            ? (titleEl.getAttribute('alt') || titleEl.textContent || '').trim()
            : '';

        let price = 0;
        if (priceEl) {
            const pt = (priceEl.textContent || '').replace(/[^0-9]/g, '');
            price = parseInt(pt, 10) || 0;
        }

        const image = imageEl
            ? (imageEl.getAttribute('src') || imageEl.getAttribute('data-src') || '')
            : '';

        items.push({
            id: id,
            name: title,
            price: price,
            photos: image ? [image] : [],
            item_url: 'https://jp.mercari.com' + href,
            status: 'STATUS_ON_SALE',
            created: 0,
            brand: '',
            description: '',
        });
    });

    return JSON.stringify(items);
}
"""


def _int_to_bytes(n: int) -> bytes:
    return n.to_bytes((n.bit_length() + 7) // 8, byteorder="big")


def _b64url(data: bytes) -> str:
    return urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _generate_dpop(*, uuid: str, method: str, url: str) -> str:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    pub_nums = public_key.public_numbers()

    header = {
        "typ": "dpop+jwt",
        "alg": "ES256",
        "jwk": {
            "crv": "P-256",
            "kty": "EC",
            "x": _b64url(_int_to_bytes(pub_nums.x)),
            "y": _b64url(_int_to_bytes(pub_nums.y)),
        },
    }

    payload = {
        "iat": int(now()),
        "jti": uuid,
        "htu": url,
        "htm": method.upper(),
    }

    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    data_to_sign = f"{header_b64}.{payload_b64}".encode()

    signature = private_key.sign(data_to_sign, ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(signature)
    sig_b64 = _b64url(_int_to_bytes(r) + _int_to_bytes(s))

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def _convert_booleans(obj: Any) -> Any:
    if isinstance(obj, bool):
        return str(obj).lower()
    if isinstance(obj, dict):
        return {k: _convert_booleans(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_convert_booleans(i) for i in obj]
    return obj


async def search_mercari_jp(
    query: str,
    limit: int = 500,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    sort: str = "SORT_CREATED_TIME",
    order: str = "ORDER_DESC",
) -> list[dict]:
    async def _try_api() -> list[dict]:
        return await _search_api(query, limit, price_min, price_max, sort, order)

    async def _try_rsc() -> list[dict]:
        return await _search_rsc(query, limit)

    async def _try_bs_ssr() -> list[dict]:
        return await _search_bs(query, limit)

    async def _try_pw() -> list[dict]:
        return await _search_playwright(query, limit)

    stages = [
        ("API", _try_api),
        ("RSC", _try_rsc),
        ("BS.SSR", _try_bs_ssr),
        ("Playwright", _try_pw),
    ]

    for stage_name, stage_fn in stages:
        try:
            items = await stage_fn()
            if items:
                logger.info(
                    "Mercari JP %s: found %d items for query='%s'",
                    stage_name, len(items), query,
                )
                return items
            logger.debug("Mercari JP %s: 0 items", stage_name)
        except Exception as e:
            logger.warning("Mercari JP %s error: %s", stage_name, e, exc_info=True)

    logger.warning("Mercari JP all methods returned 0 items for query='%s'", query)
    return []


async def _search_rsc(query: str, limit: int = 500) -> list[dict]:
    logger.info("Mercari JP RSC: fetching SSR page for query='%s'", query)
    headers = {
        "User-Agent": MERCARI_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en;q=0.9",
        "Referer": "https://jp.mercari.com/",
    }
    params = {"keyword": query, "status": "on_sale"}

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(SEARCH_PAGE_URL, params=params, headers=headers)

            if resp.status_code != 200:
                logger.warning("Mercari JP RSC: HTTP %d", resp.status_code)
                return []

            html = resp.text
            logger.debug("Mercari JP RSC: html_len=%d", len(html))

            items = parse_rsc_items(html)
            if items:
                logger.info("Mercari JP RSC: found %d items", len(items))
                return items[:limit]

            logger.debug("Mercari JP RSC: no items via RSC parser")
            return []
    except Exception as e:
        logger.error("Mercari JP RSC error: %s", e)
        return []


async def _search_bs(query: str, limit: int = 500) -> list[dict]:
    logger.info("Mercari JP BS.SSR: fetching page for query='%s'", query)
    headers = {
        "User-Agent": MERCARI_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en;q=0.9",
        "Referer": "https://jp.mercari.com/",
    }
    params = {"keyword": query, "status": "on_sale"}

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(SEARCH_PAGE_URL, params=params, headers=headers)

            if resp.status_code != 200:
                return []

            html = resp.text
            soup = BeautifulSoup(html, "lxml")

            items: list[dict] = []
            seen_ids: set[str] = set()

            for link in soup.select("a[href*='/item/m']"):
                href = link.get("href", "")
                m = re.search(r"/item/(m\d+)", href)
                if not m:
                    continue
                item_id = m.group(1)
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)

                img = link.select_one("img")
                title = ""
                if img:
                    title = img.get("alt", "") or img.get("title", "") or ""

                if not title:
                    title_el = link.select_one("[class*='name'], [class*='title'], h3, h4")
                    if title_el:
                        title = title_el.get_text(strip=True)

                price_el = link.select_one("[class*='price']")
                price = 0
                if price_el:
                    price_text = re.sub(r"[^\d]", "", price_el.get_text(strip=True))
                    try:
                        price = int(price_text) if price_text else 0
                    except ValueError:
                        price = 0

                img_src = img.get("src", "") if img else ""

                items.append({
                    "id": item_id,
                    "name": title,
                    "price": price,
                    "photos": [img_src] if img_src else [],
                    "item_url": f"https://jp.mercari.com/item/{item_id}",
                    "status": "STATUS_ON_SALE",
                    "created": 0,
                    "brand": "",
                    "description": "",
                })

            items = [i for i in items if i["name"] and i["price"] > 0]

            logger.info(
                "Mercari JP BS.SSR: found %d items (html_len=%d)",
                len(items), len(html),
            )
            return items[:limit]

    except Exception as e:
        logger.error("Mercari JP BS.SSR error: %s", e)
        return []


async def _search_api(
    query: str,
    limit: int = 500,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    sort: str = "SORT_CREATED_TIME",
    order: str = "ORDER_DESC",
) -> list[dict]:
    page_size = min(limit, 120)
    session_id = f"MERCARI_BOT_{uuid.uuid4()}"

    payload: dict[str, Any] = {
        "userId": f"MERCARI_BOT_{uuid.uuid4()}",
        "pageSize": page_size,
        "pageToken": "v1:0",
        "searchSessionId": session_id,
        "indexRouting": "INDEX_ROUTING_UNSPECIFIED",
        "searchCondition": {
            "keyword": query,
            "sort": sort,
            "order": order,
            "status": ["STATUS_ON_SALE"],
            "excludeKeyword": "",
        },
        "withAuction": True,
        "defaultDatasets": ["DATASET_TYPE_MERCARI", "DATASET_TYPE_BEYOND"],
    }

    if price_min is not None:
        payload["searchCondition"]["priceMin"] = price_min
    if price_max is not None:
        payload["searchCondition"]["priceMax"] = price_max

    all_items: list[dict] = []

    headers = {
        "X-Platform": "web",
        "Accept": "*/*",
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": MERCARI_UA,
        "Origin": "https://jp.mercari.com",
        "Referer": "https://jp.mercari.com/",
    }

    urls_to_try = [SEARCH_URL_V2, SEARCH_URL_V3]

    async with httpx.AsyncClient(timeout=30) as client:
        for search_url in urls_to_try:
            if all_items:
                break

            logger.debug("Mercari API trying: %s", search_url)
            payload["pageToken"] = "v1:0"
            max_pages = 5

            for _ in range(max_pages):
                if len(all_items) >= limit:
                    break

                dpop = _generate_dpop(
                    uuid=str(uuid.uuid4()),
                    method="POST",
                    url=search_url,
                )
                headers["DPoP"] = dpop
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

                try:
                    resp = await client.post(
                        search_url,
                        content=body,
                        headers=headers,
                    )
                    logger.debug(
                        "Mercari API %s status=%d body=%s",
                        search_url, resp.status_code, resp.text[:300],
                    )

                    if resp.status_code == 400:
                        logger.warning("Mercari API %s: 400 error: %s", search_url, resp.text[:200])
                        break

                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    logger.error("Mercari JP API error on %s: %s", search_url, e)
                    break

                items = data.get("items", [])
                if not items:
                    logger.debug("Mercari API %s: no items in response", search_url)
                    break

                for item in items:
                    all_items.append(_remap_item(item))
                    if len(all_items) >= limit:
                        break

                next_token = data.get("meta", {}).get("nextPageToken")
                if not next_token:
                    break
                payload["pageToken"] = next_token

    return all_items


async def _search_playwright(query: str, limit: int = 500) -> list[dict]:
    try:
        from patchright.async_api import async_playwright as _pw
    except ImportError:
        from playwright.async_api import async_playwright as _pw

    url = f"{SEARCH_PAGE_URL}?keyword={query}&status=on_sale"

    logger.info("Mercari JP Playwright navigating to %s", url)

    async with _pw() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-web-security",
            ],
        )

        context = await browser.new_context(
            user_agent=MERCARI_UA,
            viewport={"width": 1920, "height": 1080},
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            java_script_enabled=True,
            bypass_csp=True,
            ignore_https_errors=True,
            extra_http_headers={
                "Accept-Language": "ja,en;q=0.9",
            },
        )

        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(random.uniform(2, 4))

            for attempt in range(5):
                title = await page.title()
                body_text = await page.evaluate("document.body?.innerText?.substring(0, 200) || ''")
                logger.debug(
                    "Mercari JP PW attempt %d: title='%s', body='%s'",
                    attempt + 1, title, body_text[:80],
                )

                if "Just a moment" not in title:
                    item_count = await page.evaluate(
                        "document.querySelectorAll('a[href*=\"/item/m\"]').length"
                    )
                    if item_count > 0:
                        logger.info(
                            "Mercari JP PW: found %d item links on attempt %d",
                            item_count, attempt + 1,
                        )
                        break

                    logger.info(
                        "Mercari JP PW: no items yet (attempt %d/5), waiting...",
                        attempt + 1,
                    )

                    await asyncio.sleep(random.uniform(2, 4))

            try:
                await page.wait_for_selector("a[href*='/item/m']", timeout=15000)
            except Exception:
                logger.warning("Mercari JP PW: timeout waiting for item links")

            # Scroll to load more items
            seen_count = 0
            scroll_attempts = 0
            max_scroll = 15
            while scroll_attempts < max_scroll:
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await asyncio.sleep(random.uniform(0.8, 1.5))
                current_count = await page.evaluate(
                    "document.querySelectorAll('a[href*=\"/item/m\"]').length"
                )
                if current_count > seen_count:
                    logger.debug(
                        "Mercari JP PW scroll %d: items increased %d -> %d",
                        scroll_attempts + 1, seen_count, current_count,
                    )
                    seen_count = current_count
                    scroll_attempts = 0
                else:
                    scroll_attempts += 1
                if current_count >= limit:
                    break

            logger.info("Mercari JP PW: after scroll, total items=%d", seen_count)

            raw = await page.evaluate(EXTRACT_ITEMS_JS)
            items_data: list[dict] = json.loads(raw) if raw else []

            html_len = len(await page.content())
            logger.info(
                "Mercari JP PW: extracted %d items, html_len=%d",
                len(items_data), html_len,
            )

            return items_data[:limit]

        except Exception as e:
            logger.error("Mercari JP PW error: %s", e, exc_info=True)
            return []
        finally:
            await page.close()
            await context.close()
            await browser.close()


def _remap_item(item: dict) -> dict:
    item_id = item.get("id", "")
    item_url = f"https://jp.mercari.com/item/{item_id}"
    brand_raw = item.get("itemBrand") or item.get("brand")
    brand_name = ""
    if isinstance(brand_raw, dict):
        brand_name = brand_raw.get("name", "")
    elif isinstance(brand_raw, str):
        brand_name = brand_raw
    elif brand_raw is None:
        brand_name = ""
    return {
        "id": item_id,
        "name": item.get("name", ""),
        "price": item.get("price", 0),
        "photos": item.get("thumbnails", []),
        "status": item.get("status", ""),
        "created": item.get("created", 0),
        "updated": item.get("updated", 0),
        "item_url": item_url,
        "brand": brand_name,
        "description": item.get("description") or item.get("shortDescription") or "",
    }
