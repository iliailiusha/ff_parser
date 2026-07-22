import asyncio
import logging
import random
from typing import Optional

from goofish_parser.carousell_scraper import CAROUSELL_UA
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

// Override oscpu (Firefox)
Object.defineProperty(navigator, 'oscpu', { get: () => 'Windows NT 10.0; Win64; x64' });

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

// Override WebGL2
try {
    const proto2 = WebGL2RenderingContext.prototype;
    const origGetParam2 = proto2.getParameter;
    proto2.getParameter = function(param) {
        if (param === 37445) return 'Intel Inc.';
        if (param === 37446) return 'Intel(R) UHD Graphics 630';
        return origGetParam2.call(this, param);
    };
} catch(e) {}

// Remove webdriver from navigator fully
try {
    delete navigator.__proto__.webdriver;
} catch(e) {}
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


class CarousellBrowserAuth:
    async def get_cookies_and_html(
        self,
        url: str,
        timeout: int = 120,
    ) -> tuple[dict[str, str], str]:
        xvfb = await get_xvfb()
        if not xvfb.is_running():
            logger.warning("Xvfb not running, proceeding without virtual display")

        for engine in ("chromium", "firefox"):
            try:
                result = await self._try_engine(engine, url, timeout)
                if result:
                    cookies, html = result
                    has_cf = "cf_clearance" in cookies
                    has_content = len(html) > 1000 and "Just a moment" not in html[:500]
                    if has_content or has_cf:
                        logger.info(
                            "Carousell %s: success (cf_clearance=%s, html_len=%d)",
                            engine, has_cf, len(html),
                        )
                        return result
                    logger.warning("Carousell %s: Cloudflare still blocking", engine)
            except Exception as e:
                logger.warning("Carousell %s engine failed: %s", engine, e)

        return {}, ""

    async def _try_engine(
        self, engine: str, url: str, timeout: int
    ) -> Optional[tuple[dict[str, str], str]]:
        if engine == "chromium":
            return await self._run_patchright(url, timeout)
        return await self._run_firefox(url, timeout)

    async def _run_patchright(
        self, url: str, timeout: int
    ) -> Optional[tuple[dict[str, str], str]]:
        try:
            from patchright.async_api import async_playwright as _pw
        except ImportError:
            logger.warning("patchright not installed, falling back to playwright")
            from playwright.async_api import async_playwright as _pw

        async with _pw() as pw:
            browser = await pw.chromium.launch(
                headless=False,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-features=ChromeWhatsNewUI",
                    "--disable-features=ChromeLabs",
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-field-trial-config",
                    "--disable-ipc-flooding-protection",
                    "--window-size=1920,1080",
                    f"--window-position={random.randint(0, 50)},{random.randint(0, 50)}",
                ],
            )

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
                logger.info("Carousell patchright navigating to %s", url)
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                await _human_delay(1000, 2000)

                for attempt in range(10):
                    title = await page.title()
                    content_snippet = await page.evaluate(
                        "document.body?.innerText?.substring(0, 200) || ''"
                    )

                    logger.debug(
                        "Carousell patchright attempt %d: title='%s', snippet='%s'",
                        attempt + 1, title, content_snippet[:80],
                    )

                    has_challenge = await self._detect_challenge(page)
                    if not has_challenge and "Just a moment" not in title:
                        logger.info("Carousell patchright: Cloudflare passed")
                        break

                    logger.info(
                        "Carousell patchright: waiting for Cloudflare (attempt %d/10)",
                        attempt + 1,
                    )

                    if attempt == 3:
                        await _random_scroll(page)
                        await _random_mouse_move(page)

                    if attempt == 6:
                        await page.reload(wait_until="domcontentloaded")
                        await _human_delay(1500, 3000)

                    await asyncio.sleep(random.uniform(3, 6))

                await asyncio.sleep(random.uniform(2, 4))

                raw_cookies = await context.cookies()
                cookies: dict[str, str] = {}
                for c in raw_cookies:
                    name = c.get("name", "")
                    value = c.get("value", "")
                    if name and value:
                        cookies[name] = value

                html = await page.content()

                logger.info(
                    "Carousell patchright: %d cookies (cf_clearance=%s), HTML=%d, title=%s",
                    len(cookies),
                    "cf_clearance" in cookies,
                    len(html),
                    await page.title(),
                )
                return cookies, html

            except Exception as e:
                logger.error("Carousell patchright error: %s", e)
                return None
            finally:
                await page.close()
                await context.close()
                await browser.close()

    async def _run_firefox(
        self, url: str, timeout: int
    ) -> Optional[tuple[dict[str, str], str]]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("playwright not installed for Firefox fallback")
            return None

        async with async_playwright() as pw:
            browser = await pw.firefox.launch(
                headless=False,
                args=[
                    "--no-sandbox",
                ],
            )

            context = await browser.new_context(
                user_agent=CAROUSELL_UA,
                viewport={"width": 1920, "height": 1080},
                screen={"width": 1920, "height": 1080},
                locale="en-US",
                timezone_id="Asia/Singapore",
                java_script_enabled=True,
                bypass_csp=True,
                ignore_https_errors=True,
            )

            page = await context.new_page()

            try:
                logger.info("Carousell Firefox navigating to %s", url)
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                await _human_delay(1500, 3000)

                for attempt in range(8):
                    title = await page.title()
                    if "Just a moment" not in title:
                        logger.info("Carousell Firefox: Cloudflare passed")
                        break
                    logger.info(
                        "Carousell Firefox: waiting (attempt %d/8)", attempt + 1
                    )
                    if attempt == 4:
                        await page.reload(wait_until="domcontentloaded")
                    await asyncio.sleep(random.uniform(3, 5))

                await asyncio.sleep(random.uniform(2, 4))

                raw_cookies = await context.cookies()
                cookies: dict[str, str] = {}
                for c in raw_cookies:
                    name = c.get("name", "")
                    value = c.get("value", "")
                    if name and value:
                        cookies[name] = value

                html = await page.content()

                logger.info(
                    "Carousell Firefox: %d cookies, HTML=%d, title=%s",
                    len(cookies), len(html), await page.title(),
                )
                return cookies, html

            except Exception as e:
                logger.error("Carousell Firefox error: %s", e)
                return None
            finally:
                await page.close()
                await context.close()
                await browser.close()

    async def _detect_challenge(self, page: object) -> bool:
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
