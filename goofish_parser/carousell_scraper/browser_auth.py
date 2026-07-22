import asyncio
import logging
from typing import Optional

from goofish_parser.services.user_agent import get_random_ua

logger = logging.getLogger(__name__)

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
window.chrome = { runtime: {} };
// Override permissions
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
    Promise.resolve({ state: Notification.permission }) :
    originalQuery(parameters)
);
"""


class CarousellBrowserAuth:
    async def get_cookies_and_html(
        self,
        url: str,
        timeout: int = 90,
    ) -> tuple[dict[str, str], str]:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                ],
            )

            context = await browser.new_context(
                user_agent=get_random_ua(),
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                timezone_id="Asia/Singapore",
                java_script_enabled=True,
                bypass_csp=True,
                ignore_https_errors=True,
            )

            await context.add_init_script(STEALTH_JS)

            page = await context.new_page()

            try:
                logger.info("Carousell browser navigating to %s", url)
                await page.goto(url, wait_until="load", timeout=timeout * 1000)

                await page.wait_for_timeout(10000)

                for attempt in range(6):
                    title = await page.title()
                    if "Just a moment" not in title:
                        logger.info("Carousell browser: Cloudflare passed on attempt %d", attempt + 1)
                        break
                    logger.info("Carousell browser: still waiting for Cloudflare (attempt %d)", attempt + 1)
                    await page.wait_for_timeout(5000)
                else:
                    logger.warning("Carousell browser: Cloudflare still blocking after all attempts")

                raw_cookies = await context.cookies()
                cookies: dict[str, str] = {}
                for c in raw_cookies:
                    name = c.get("name", "")
                    value = c.get("value", "")
                    if name and value:
                        cookies[name] = value

                html = await page.content()

                logger.info(
                    "Carousell browser: got %d cookies, HTML length=%d, title=%s",
                    len(cookies), len(html), await page.title(),
                )
                return cookies, html

            except Exception as e:
                logger.error("Carousell browser auth error: %s", e)
                raise
            finally:
                await page.close()
                await context.close()
                await browser.close()
