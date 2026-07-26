import asyncio
import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from playwright.async_api import TimeoutError as PwTimeoutError

from goofish_parser.carousell_scraper import CAROUSELL_UA
from goofish_parser.config import (
    CAROUSELL_PROXIES,
    CAROUSELL_PROXY_ROTATION,
    CAROUSELL_TIMEOUT,
    CAROUSELL_HEADLESS,
    CAROUSELL_MAX_ROUNDS,
    CAROUSELL_MAX_CF_ATTEMPTS,
    CAROUSELL_CF_BACKOFF_BASE,
    CAROUSELL_PROXY_TIMEOUT,
    CAROUSELL_EXTRA_HEADERS_JSON,
)
from goofish_parser.services.xvfb_manager import get_xvfb
from goofish_parser.carousell_scraper.cookie_manager import CarousellCookieManager

logger = logging.getLogger(__name__)
_cookie_manager = CarousellCookieManager()

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


# ── Helpers ──────────────────────────────────────────────────────────

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
        try:
            title = await page.title()
            if "Just a moment" in title:
                return True
        except Exception:
            pass
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


async def _try_solve_turnstile(page: object) -> bool:
    try:
        frames = page.frames
        for frame in frames:
            url = frame.url
            if "turnstile" in url or "challenge" in url:
                checkbox = await frame.query_selector("#checkbox")
                if checkbox:
                    await checkbox.click()
                    await asyncio.sleep(2)
                    return True
        turnstile_iframe = await page.query_selector("iframe[src*='turnstile'], iframe[src*='challenge']")
        if turnstile_iframe:
            frame = await turnstile_iframe.content_frame()
            if frame:
                cb = await frame.query_selector("#checkbox")
                if cb:
                    await cb.click()
                    await asyncio.sleep(2)
                    return True
    except Exception:
        pass
    return False


# ── Proxy Pool ───────────────────────────────────────────────────────

@dataclass
class _ProxyPool:
    proxies: list[str] = field(default_factory=list)
    rotation: str = "roundrobin"
    _index: int = 0
    _dead_until: dict[str, datetime] = field(default_factory=dict)
    _dead_cooldown: timedelta = timedelta(minutes=5)

    @classmethod
    def from_config(cls) -> "_ProxyPool":
        return cls(
            proxies=list(CAROUSELL_PROXIES),
            rotation=CAROUSELL_PROXY_ROTATION,
        )

    def get(self) -> Optional[str]:
        alive = [p for p in self.proxies if p not in self._dead_until or datetime.now() > self._dead_until[p]]
        if not alive:
            logger.warning("All proxies are dead, clearing cooldown")
            self._dead_until.clear()
            alive = list(self.proxies)
        if not alive:
            return None
        if self.rotation == "random":
            return random.choice(alive)
        self._index = (self._index + 1) % len(alive)
        return alive[self._index]

    def mark_dead(self, proxy: str) -> None:
        if proxy:
            self._dead_until[proxy] = datetime.now() + self._dead_cooldown
            logger.info("Proxy marked dead for %s: %s", self._dead_cooldown, proxy)

    def mark_alive(self, proxy: str) -> None:
        if proxy and proxy in self._dead_until:
            del self._dead_until[proxy]


# ── Session Manager ─────────────────────────────────────────────────

@dataclass
class _SessionManager:
    manager: CarousellCookieManager = field(default_factory=lambda: _cookie_manager)
    _cookies: dict[str, str] = field(default_factory=dict)

    def load(self) -> dict[str, str]:
        self._cookies = self.manager.load()
        return self._cookies

    def is_valid(self) -> bool:
        return self.manager.is_valid(self._cookies)

    def update(self, cookies: dict[str, str]) -> None:
        if not cookies:
            return
        self._cookies.update(cookies)
        self.manager.save(self._cookies)

    def to_context_cookies(self, domain: str) -> list[dict[str, str]]:
        if not self._cookies:
            return []
        return [
            {"name": name, "value": value, "domain": f".{domain}", "path": "/"}
            for name, value in self._cookies.items()
        ]


# ── Main search ─────────────────────────────────────────────────────

async def search_carousell_pw(
    query: str,
    count: int = 50,
    country: str = "SG",
    sort: int = 3,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
) -> list[dict]:
    domains = {
        "SG": "www.carousell.sg",
        "MY": "www.carousell.com.my",
        "PH": "www.carousell.ph",
        "ID": "www.carousell.co.id",
        "HK": "www.carousell.com.hk",
        "TW": "www.carousell.com.tw",
    }
    domain = domains.get(country, domains["SG"])

    api_items = await _search_via_api(query, count, domain, sort, price_min, price_max)
    if api_items:
        logger.info("Carousell API returned %d items for query='%s'", len(api_items), query)
        return api_items

    logger.info("Carousell API returned 0 items, falling back to Playwright")
    return await _search_via_playwright(query, count, domain, sort, price_min, price_max)


# ── Playwright search (refactored) ──────────────────────────────────

async def _search_via_playwright(
    query: str,
    count: int,
    domain: str,
    sort: int = 3,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
) -> list[dict]:
    xvfb = await get_xvfb()
    if not xvfb.is_running():
        logger.warning("Xvfb not running, proceeding without virtual display")

    sort_map = {1: "price_asc", 2: "price_desc", 3: "time_created_desc"}
    sort_str = sort_map.get(sort, "time_created_desc")
    params = f"q={query}&sort={sort_str}"
    if price_min is not None:
        params += f"&sp={price_min}"
    if price_max is not None:
        params += f"&ep={price_max}"
    url = f"https://{domain}/search/?{params}"

    logger.info("Carousell Playwright search: %s", url)

    try:
        from patchright.async_api import async_playwright as _pw
    except ImportError:
        from playwright.async_api import async_playwright as _pw

    extra_headers: dict[str, str] = json.loads(CAROUSELL_EXTRA_HEADERS_JSON) if CAROUSELL_EXTRA_HEADERS_JSON else {}
    session = _SessionManager()
    session.load()
    proxy_pool = _ProxyPool.from_config()
    cf_consecutive_fail = 0
    CF_CONSECUTIVE_FAIL_LIMIT = 3

    for round_idx in range(CAROUSELL_MAX_ROUNDS):
        if cf_consecutive_fail >= CF_CONSECUTIVE_FAIL_LIMIT:
            logger.warning("Fast-fail: %d consecutive CF blocks, aborting", cf_consecutive_fail)
            break

        proxy = proxy_pool.get()
        browser = None
        context = None
        page = None

        try:
            async with _pw() as pw:
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
                        "--disable-webgl",
                        "--window-size=1920,1080",
                        f"--window-position={random.randint(0, 200)},{random.randint(0, 200)}",
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
                        **extra_headers,
                    },
                )

                if session.is_valid():
                    ck = session.to_context_cookies(domain)
                    if ck:
                        await context.add_cookies(ck)
                        logger.info("Reusing %d saved cookies for Carousell", len(ck))

                await context.add_init_script(COMPREHENSIVE_STEALTH)
                page = await context.new_page()

                await page.route("**/*", lambda route, request: (
                    route.abort() if request.resource_type in ("image", "media", "font")
                    else route.continue_()
                ))

                logger.info("[carousell] PW navigating to %s (round %d/%d)", url, round_idx + 1, CAROUSELL_MAX_ROUNDS)
                await page.goto(url, wait_until="domcontentloaded", timeout=CAROUSELL_TIMEOUT * 1000)
                await _human_delay(1500, 3000)

                cf_passed = await _handle_cf_challenge(page, round_idx, url)
                if not cf_passed:
                    cf_consecutive_fail += 1
                    proxy_pool.mark_dead(proxy) if proxy else None
                    logger.warning("Carousell PW: CF block (round %d, consecutive %d)", round_idx + 1, cf_consecutive_fail)
                    continue

                cf_consecutive_fail = 0
                proxy_pool.mark_alive(proxy) if proxy else None

                await _human_delay(2000, 4000)

                items_data = await _extract_items(page, count)
                items_data = _apply_price_filter(items_data, price_min, price_max)

                fresh_cf = await _extract_cookies(context)
                if fresh_cf:
                    session.update(fresh_cf)

                logger.info("Carousell PW: returning %d items for query='%s'", len(items_data), query)
                return items_data

        except PwTimeoutError as e:
            logger.error("Carousell PW timeout (round %d): %s", round_idx + 1, e)
            proxy_pool.mark_dead(proxy) if proxy else None
        except Exception as e:
            logger.error("Carousell PW error (round %d): %s: %s", round_idx + 1, type(e).__name__, e)
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            if context:
                try:
                    await context.close()
                except Exception:
                    pass
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

        if round_idx < CAROUSELL_MAX_ROUNDS - 1:
            backoff = CAROUSELL_CF_BACKOFF_BASE * (2 ** round_idx)
            logger.info("Carousell PW: backing off %.1f seconds before next round", backoff)
            await asyncio.sleep(backoff)

    logger.warning("Carousell PW: all %d rounds failed", CAROUSELL_MAX_ROUNDS)
    return []


async def _handle_cf_challenge(page: object, round_idx: int, url: str) -> bool:
    for cf_attempt in range(CAROUSELL_MAX_CF_ATTEMPTS):
        title = await page.title()
        has_challenge = await _detect_challenge(page)

        logger.debug(
            "[carousell] CF attempt %d: title='%s' challenge=%s",
            cf_attempt + 1, title, has_challenge,
        )

        if not has_challenge and "Just a moment" not in title:
            logger.info("[carousell] Cloudflare passed (round %d, cf_attempt %d)", round_idx + 1, cf_attempt + 1)
            return True

        # Try solving turnstile on first attempt
        if cf_attempt == 0:
            solved = await _try_solve_turnstile(page)
            if solved:
                logger.info("[carousell] Turnstile checkbox clicked")

        # Fast fail: if we've been trying for too long, move to next round
        logger.info("[carousell] waiting for Cloudflare (attempt %d/%d, round %d)", cf_attempt + 1, CAROUSELL_MAX_CF_ATTEMPTS, round_idx + 1)

        if cf_attempt > 0 and cf_attempt % 2 == 0:
            logger.info("[carousell] reloading page (cf_attempt %d)", cf_attempt + 1)
            try:
                await page.reload(wait_until="domcontentloaded")
            except Exception:
                pass
            await _human_delay(2000, 4000)

        # Quick wait for CF to resolve (3-5s)
        try:
            await page.wait_for_function(
                "document.title.indexOf('Just a moment') === -1 && document.querySelector('body')?.innerText?.indexOf('Just a moment') === -1",
                timeout=random.randint(3000, 5000),
            )
        except Exception:
            pass

    logger.warning("[carousell] Cloudflare challenge failed after %d attempts", CAROUSELL_MAX_CF_ATTEMPTS)
    return False


async def _extract_items(page: object, count: int) -> list[dict]:
    for selector in CAROUSELL_ITEM_SELECTORS:
        try:
            await page.wait_for_selector(selector, timeout=10000)
            logger.info("Carousell PW: found items with selector '%s'", selector)
            break
        except Exception:
            continue
    else:
        logger.warning("Carousell PW: no item selectors matched")
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

    return items_data[:count]


async def _extract_cookies(context: object) -> dict[str, str]:
    try:
        pw_cookies = await context.cookies()
        fresh = {
            c["name"]: c["value"]
            for c in pw_cookies
            if c["name"] in ("cf_clearance", "__cf_bm", "_cfuvid")
        }
        return fresh
    except Exception:
        return {}


# ── GraphQL API fallback ────────────────────────────────────────────

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

    cookies = _cookie_manager.load()
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items()) if cookies else ""

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
            if cookie_header:
                api_headers["Cookie"] = cookie_header

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

            set_cookie = resp.headers.get("set-cookie", "")
            if set_cookie and "cf_clearance" in set_cookie:
                for part in set_cookie.split(";"):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        cookies[k.strip()] = v.strip()
                _cookie_manager.save(cookies)
                cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())

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
