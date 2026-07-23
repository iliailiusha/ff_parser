import asyncio
import json
import logging
import random
from typing import Any, Optional

from goofish_parser.carousell_scraper import CAROUSELL_UA
from goofish_parser.config import CAROUSELL_PROXIES, CAROUSELL_PROXY_ROTATION, CAROUSELL_TIMEOUT, CAROUSELL_HEADLESS
from goofish_parser.services.xvfb_manager import get_xvfb

logger = logging.getLogger(__name__)

CF_CHALLENGE_SELECTORS = [
    "#cf-challenge-wrapper",
    "#cf-hcaptcha-container",
    "#challenge-form",
    "iframe[src*='challenge']",
    "iframe[src*='turnstile']",
    ".cf-browser-verification",
    "#TurnstileWidget",
]

CAROUSELL_ITEM_SELECTORS = [
    "a[href*='/p/']",
    "div[data-testid='listing-card']",
    "div.listing-card",
    "div[class*='listing'] a[href]",
    "div.search-result a[href]",
    "div[class*='card'] a[href*='/p/']",
    "div[class*='item'] a[href*='/p/']",
]

COMPREHENSIVE_STEALTH = """
// Override webdriver
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// Override plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
        { name: 'Native Client', filename: 'internal-nacl-plugin' },
    ],
    length: 3,
});

// Override languages
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en', 'zh-CN'] });

// Chrome runtime
window.chrome = {
    runtime: {},
    loadTimes: function() {},
    csi: function() {},
    app: {},
};

// Override permissions
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters)
);

// Hardware concurrency
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });

// Device memory
Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });

// Connection
Object.defineProperty(navigator, 'connection', {
    get: () => ({ effectiveType: '4g', rtt: 50, downlink: 10, saveData: false }),
});

// Override platform
Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });

// Override WebGL vendor/renderer
try {
    const proto = WebGLRenderingContext.prototype;
    const origGetParam = proto.getParameter;
    proto.getParameter = function(param) {
        if (param === 37445) return 'Intel Inc.';
        if (param === 37446) return 'Intel(R) UHD Graphics 630';
        return origGetParam.call(this, param);
    };
} catch(e) {}

try {
    const proto2 = WebGL2RenderingContext.prototype;
    const origGetParam2 = proto2.getParameter;
    proto2.getParameter = function(param) {
        if (param === 37445) return 'Intel Inc.';
        if (param === 37446) return 'Intel(R) UHD Graphics 630';
        return origGetParam2.call(this, param);
    };
} catch(e) {}

try {
    delete navigator.__proto__.webdriver;
} catch(e) {}
"""

EXTRACT_ITEMS_JS = """
() => {
    const items = [];
    const cards = document.querySelectorAll('a[href*="/p/"], div[data-testid="listing-card"], div.listing-card');

    const seen = new Set();

    cards.forEach(card => {
        const link = card.tagName === 'A' ? card : card.querySelector('a[href*="/p/"]');
        if (!link) return;
        const href = link.getAttribute('href') || '';
        const id = href.match(/\\/p\\/([^\\/?#&]+)/)?.[1] || href;
        if (seen.has(id)) return;
        seen.add(id);

        const titleEl = card.querySelector('[data-testid="title"], .title, h3, h4, [class*="title"]');
        const priceEl = card.querySelector('[data-testid="price"], .price, [class*="price"]');
        const imageEl = card.querySelector('img[src], img[data-src]');
        const locationEl = card.querySelector('[data-testid="location"], .location, [class*="location"]');
        const conditionEl = card.querySelector('[data-testid="condition"], .condition, [class*="condition"]');

        const title = titleEl ? (titleEl.textContent || '').trim() : '';
        if (!title) return;

        const priceText = priceEl ? (priceEl.textContent || '').trim() : '';
        const price = parseFloat(priceText.replace(/[^0-9.]/g, '')) || 0;

        const image = imageEl ? (imageEl.getAttribute('src') || imageEl.getAttribute('data-src') || '') : '';
        const location = locationEl ? (locationEl.textContent || '').trim() : '';
        const condition = conditionEl ? (conditionEl.textContent || '').trim() : '';

        const url = href.startsWith('http') ? href : 'https://www.carousell.sg' + href;

        items.push({
            id: id,
            title: title,
            price: price,
            image: image,
            location: location,
            condition: condition,
            url: url,
        });
    });

    return JSON.stringify(items);
}
"""


async def _human_delay(min_ms: float = 100, max_ms: float = 600) -> None:
    await asyncio.sleep(random.uniform(min_ms, max_ms) / 1000)


async def _random_scroll(page: object) -> None:
    try:
        for _ in range(random.randint(1, 3)):
            x = random.randint(0, 300)
            y = random.randint(100, 700)
            await page.evaluate(f"window.scrollTo({x}, {y})")
            await _human_delay(200, 800)
    except Exception:
        pass


async def _random_mouse_move(page: object) -> None:
    try:
        for _ in range(random.randint(2, 5)):
            x = random.randint(100, 1800)
            y = random.randint(100, 900)
            await page.mouse.move(x, y, steps=random.randint(5, 15))
            await _human_delay(50, 200)
    except Exception:
        pass


async def _detect_challenge(page: object) -> bool:
    try:
        for selector in CF_CHALLENGE_SELECTORS:
            elem = await page.query_selector(selector)
            if elem:
                return True
        body_text = await page.evaluate(
            "document.body?.innerText?.substring(0, 500) || ''"
        )
        challenge_keywords = [
            "checking your browser",
            "please wait",
            "cf-ray",
            "cloudflare",
            "turnstile",
            "security check",
        ]
        for kw in challenge_keywords:
            if kw.lower() in body_text.lower():
                return True
        return False
    except Exception:
        return False


def _get_proxy() -> Optional[str]:
    if not CAROUSELL_PROXIES:
        return None
    if CAROUSELL_PROXY_ROTATION == "random":
        return random.choice(CAROUSELL_PROXIES)
    idx = random.randint(0, len(CAROUSELL_PROXIES) - 1)
    return CAROUSELL_PROXIES[idx]


async def search_carousell_pw(
    query: str,
    count: int = 50,
    country: str = "SG",
    sort: int = 3,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
) -> list[dict]:
    xvfb = await get_xvfb()
    if not xvfb.is_running():
        logger.warning("Xvfb not running, proceeding without virtual display")

    domains = {
        "SG": "www.carousell.sg",
        "MY": "www.carousell.com.my",
        "PH": "www.carousell.ph",
        "ID": "www.carousell.co.id",
        "HK": "www.carousell.com.hk",
        "TW": "www.carousell.com.tw",
    }
    domain = domains.get(country, domains["SG"])

    sort_map = {1: "price_asc", 2: "price_desc", 3: "time_created_desc"}
    sort_str = sort_map.get(sort, "time_created_desc")
    params = f"q={query}&sort={sort_str}"
    if price_min is not None:
        params += f"&sp={price_min}"
    if price_max is not None:
        params += f"&ep={price_max}"
    url = f"https://{domain}/search/?{params}"

    logger.info("Carousell PW search: %s", url)

    try:
        from patchright.async_api import async_playwright as _pw
    except ImportError:
        from playwright.async_api import async_playwright as _pw

    async with _pw() as pw:
        proxy = _get_proxy()
        launch_kwargs: dict[str, Any] = {
            "headless": CAROUSELL_HEADLESS,
            "args": [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process,ChromeWhatsNewUI,ChromeLabs",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-field-trial-config",
                "--disable-ipc-flooding-protection",
                "--window-size=1920,1080",
                f"--window-position={random.randint(0, 50)},{random.randint(0, 50)}",
            ],
        }
        if proxy:
            launch_kwargs["proxy"] = {"server": proxy}

        browser = await pw.chromium.launch(**launch_kwargs)

        context = await browser.new_context(
            user_agent=CAROUSELL_UA,
            viewport={"width": 1920, "height": 1080},
            screen={"width": 1920, "height": 1080},
            no_viewport=False,
            locale="en-US",
            timezone_id="Asia/Singapore",
            java_script_enabled=True,
            bypass_csp=True,
            ignore_https_errors=True,
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
            },
        )

        await context.add_init_script(COMPREHENSIVE_STEALTH)

        page = await context.new_page()

        try:
            logger.info("Carousell PW navigating to %s", url)
            await page.goto(url, wait_until="domcontentloaded", timeout=CAROUSELL_TIMEOUT * 1000)
            await _human_delay(1000, 2000)

            for attempt in range(15):
                title = await page.title()
                content_snippet = await page.evaluate(
                    "document.body?.innerText?.substring(0, 200) || ''"
                )

                logger.debug(
                    "Carousell PW attempt %d: title='%s', snippet='%s'",
                    attempt + 1, title, content_snippet[:80],
                )

                has_challenge = await _detect_challenge(page)
                if not has_challenge and "Just a moment" not in title:
                    logger.info("Carousell PW: Cloudflare passed on attempt %d", attempt + 1)
                    break

                logger.info(
                    "Carousell PW: waiting for Cloudflare (attempt %d/15)",
                    attempt + 1,
                )

                if attempt == 3:
                    await _random_scroll(page)
                    await _random_mouse_move(page)

                if attempt == 6:
                    await page.reload(wait_until="domcontentloaded")
                    await _human_delay(1500, 3000)

                if attempt == 10:
                    logger.info("Carousell PW: reloading with different approach")
                    await page.goto(url, wait_until="domcontentloaded", timeout=CAROUSELL_TIMEOUT * 1000)
                    await _human_delay(2000, 4000)

                await asyncio.sleep(random.uniform(3, 6))

            await _human_delay(1500, 3000)

            for selector in CAROUSELL_ITEM_SELECTORS:
                try:
                    await page.wait_for_selector(selector, timeout=15000)
                    logger.info("Carousell PW: found items with selector '%s'", selector)
                    break
                except Exception:
                    continue
            else:
                logger.warning("Carousell PW: no item selectors matched, trying fallback")
                await asyncio.sleep(3)

            await _random_scroll(page)
            await _human_delay(500, 1000)

            raw = await page.evaluate(EXTRACT_ITEMS_JS)
            items_data: list[dict] = json.loads(raw) if raw else []

            html_len = len(await page.content())
            logger.info(
                "Carousell PW: extracted %d items, html_len=%d, title='%s'",
                len(items_data), html_len, await page.title(),
            )

            items_data = items_data[:count]
            items_data = _apply_price_filter(items_data, price_min, price_max)

            if items_data:
                logger.info("Carousell PW: returning %d items for query='%s'", len(items_data), query)
                return items_data

            logger.warning("Carousell PW: 0 items extracted, trying API fallback")
            return await _search_via_api(query, count, domain, sort, price_min, price_max)

        except Exception as e:
            logger.error("Carousell PW error: %s", e, exc_info=True)
            logger.info("Carousell PW: falling back to API after browser failure")
            return await _search_via_api(query, count, domain, sort, price_min, price_max)
        finally:
            await page.close()
            await context.close()
            await browser.close()


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
    try:
        from curl_cffi.requests import AsyncSession
    except ImportError:
        logger.error("curl_cffi not installed, cannot use API fallback")
        return []

    for impersonate in ("chrome124", "safari15_5"):
        try:
            ua = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
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
                logger.debug("Carousell API %s: no listings", impersonate)
                continue

            logger.info("Carousell API %s: found %d listings", impersonate, len(listings))
            items = _api_listings_to_items(listings, domain)
            items = _apply_price_filter(items, price_min, price_max)
            return items

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
    def _parse_price(val: Any) -> float:
        try:
            s = str(val).replace(",", "").replace("SGD", "").replace("$", "").replace("¥", "").strip()
            return float(s) if s else 0.0
        except (ValueError, AttributeError):
            return 0.0

    result = list(items)
    if price_min is not None:
        result = [i for i in result if _parse_price(i.get("price", 0)) >= price_min]
    if price_max is not None:
        result = [i for i in result if _parse_price(i.get("price", 0)) <= price_max]
    return result
