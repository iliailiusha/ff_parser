"""BrowserAuthenticator — генерация доверенных кук через Playwright.

Запускает Chromium, открывает goofish.com, ждёт отработки JS,
собирает все куки (включая tfstk, _m_h5_tk и др.) и возвращает их.
"""
import asyncio
import logging
from typing import Optional

from goofish_parser.config import H5_PROXIES

logger = logging.getLogger(__name__)


class BrowserAuthenticator:
    """Асинхронный генератор сессионных кук через Playwright.

    Используется, когда MtopClient получает RGV587_ERROR —
    антибот требует «живого» браузерного отпечатка.
    """

    def __init__(
        self,
        headless: bool = True,
        proxy: Optional[str] = None,
    ) -> None:
        self._headless = headless
        self._proxy = proxy or (
            f"http://{H5_PROXIES[0]}" if H5_PROXIES else None
        )

    async def get_cookies(self, url: str = "https://www.goofish.com/") -> dict[str, str]:
        """Запускает браузер, открывает страницу, собирает куки.

        Args:
            url: Стартовая страница (по умолчанию goofish.com).

        Returns:
            Словарь cookie_name -> cookie_value.
        """
        logger.info("Launching browser (headless=%s) to fetch cookies...", self._headless)

        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=self._headless,
                proxy={"server": self._proxy} if self._proxy else None,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )

            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/146.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )

            # ── stealth: подмена navigator.webdriver ──────────
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined,
                });
                // Подмена chrome.runtime
                window.chrome = {
                    runtime: {},
                };
            """)

            page = await context.new_page()

            try:
                logger.info("Navigating to %s ...", url)
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)

                # Ждём генерации антибот-кук (JS-скрипты)
                logger.info("Waiting 4s for JS execution...")
                await asyncio.sleep(4)

                # Собираем все куки из контекста
                raw_cookies = await context.cookies()
                result: dict[str, str] = {}
                for c in raw_cookies:
                    name = c.get("name", "")
                    value = c.get("value", "")
                    if name and value:
                        result[name] = value

                logger.info(
                    "Browser collected %d cookies: %s",
                    len(result), list(result.keys()),
                )
                return result

            except Exception as exc:
                logger.error("Browser auth failed: %s", exc)
                raise
            finally:
                await page.close()
                await context.close()
                await browser.close()
