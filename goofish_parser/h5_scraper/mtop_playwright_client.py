"""MtopPlaywrightClient — Safe Path: MTOP-запросы через Playwright.

В отличие от MtopClient (curl_cffi), этот клиент выполняет запросы
внутри реального браузерного контекста через page.evaluate().
Это гарантирует совпадение TLS-фингерпринта, кук и IP.

Используется как fallback, когда curl_cffi получает RGV587_ERROR.
"""
import asyncio
import hashlib
import json
import logging
import random
import time
from typing import Any, Optional
from urllib.parse import quote

from goofish_parser.config import H5_PROXIES

logger = logging.getLogger(__name__)

APP_KEY = "34839810"
MTOP_HOST = "https://h5api.m.goofish.com"

COMPREHENSIVE_STEALTH_JS = """
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
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'en', 'en-US'] });

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


class MtopPlaywrightClient:
    """MTOP-клиент, выполняющий запросы через браузерный контекст Playwright.

    Поток:
      1. start() — запускает браузер, открывает goofish.com, ждёт инициализации.
      2. request() — вычисляет MD5-подпись в Python, передаёт параметры
         в page.evaluate(), где JS-код делает fetch() к MTOP API.
      3. get_cookies() — забирает куки из контекста браузера для синхронизации.
      4. stop() — закрывает браузер.
    """

    def __init__(
        self,
        headless: bool = True,
        proxy: Optional[dict] = None,
    ) -> None:
        self._headless = headless
        if proxy is not None:
            self._proxy = proxy
        elif H5_PROXIES:
            raw = H5_PROXIES[0]
            if not raw.startswith("http://") and not raw.startswith("socks5://"):
                raw = f"http://{raw}"
            self._proxy = {"server": raw}
        else:
            self._proxy = None
        self._browser: Optional[Any] = None
        self._context: Optional[Any] = None
        self._page: Optional[Any] = None
        self._started = False

    # ── старт / стоп ───────────────────────────────────────

    async def start(self) -> None:
        """Запускает Playwright, открывает страницу, ждёт инициализации."""
        from playwright.async_api import async_playwright

        logger.info("[goofish] Starting MtopPlaywrightClient (headless=%s)...", self._headless)

        self._pw = await async_playwright().__aenter__()
        self._browser = await self._pw.chromium.launch(
            headless=self._headless,
            proxy=self._proxy,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/146.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            proxy=self._proxy,
            extra_http_headers={
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Sec-Ch-Ua": '"Chromium";v="146", "Google Chrome";v="146", "Not.A/Brand";v="24"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
            },
        )

        await self._context.add_init_script(COMPREHENSIVE_STEALTH_JS)

        self._page = await self._context.new_page()

        # Блокируем тяжёлые ресурсы для ускорения
        await self._page.route("**/*", lambda route, request: (
            route.abort() if request.resource_type in ("image", "media", "font")
            else route.continue_()
        ))

        logger.info("[goofish] Navigating to goofish.com for context init...")
        await self._page.goto(
            "https://www.goofish.com/",
            wait_until="domcontentloaded",
            timeout=30000,
        )

        # Эмуляция действий пользователя для снижения риска блока
        await self._random_scroll()
        await self._random_mouse_move()
        await asyncio.sleep(random.uniform(2, 4))

        self._started = True
        logger.info("[goofish] MtopPlaywrightClient started successfully")

    async def stop(self) -> None:
        """Останавливает браузер."""
        if not self._started:
            return
        try:
            if self._page:
                await self._page.close()
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.__aexit__(None, None, None)
        except Exception as exc:
            logger.warning("Error stopping Playwright: %s", exc)
        finally:
            self._started = False
            self._page = None
            self._context = None
            self._browser = None
            self._pw = None

    # ── запрос ─────────────────────────────────────────────

    async def request(
        self,
        api: str,
        data: dict[str, Any] | str,
        *,
        version: str = "1.0",
        extra_params: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """Выполняет MTOP-запрос внутри браузерного контекста.

        1. Вычисляет MD5-подпись в Python (токен из кук браузера).
        2. Передаёт всё в page.evaluate() для fetch().
        3. Возвращает JSON-ответ.
        """
        if not self._started:
            await self.start()

        assert self._page is not None
        assert self._context is not None

        # Получаем токен из кук браузера
        cookies_raw = await self._context.cookies()
        cookies_map = {c["name"]: c["value"] for c in cookies_raw}
        raw_tk = cookies_map.get("_m_h5_tk", "")
        token = raw_tk.split("_")[0] if "_" in raw_tk else ""

        if not token:
            raise RuntimeError("No _m_h5_tk token in browser context")

        timestamp = str(int(time.time() * 1000))
        data_str = data if isinstance(data, str) else json.dumps(data, separators=(",", ":"))
        sign = self._calc_sign(token, timestamp, data_str)

        params: dict[str, str] = {
            "jsv": "2.7.2",
            "appKey": APP_KEY,
            "t": timestamp,
            "sign": sign,
            "v": version,
            "type": "originaljson",
            "dataType": "json",
            "api": api,
            "data": data_str,
            "timeout": "20000",
        }
        if extra_params:
            params.update(extra_params)

        query_string = "&".join(
            f"{k}={quote(str(v), safe='')}" for k, v in params.items()
        )
        url = f"{MTOP_HOST}/h5/{api}/{version}/?{query_string}"

        logger.debug("PW-MTOP %s api=%s sign=%s", api, api, sign[:12])

        js_code = f"""
        (async () => {{
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 20000);
            try {{
                const resp = await fetch('{url}', {{
                    method: 'GET',
                    credentials: 'include',
                    headers: {self._js_headers()},
                    signal: controller.signal,
                }});
                clearTimeout(timeout);
                const text = await resp.text();
                return {{ok: true, data: text}};
            }} catch (e) {{
                clearTimeout(timeout);
                return {{ok: false, error: e.toString()}};
            }}
        }})()
        """

        logger.debug("[goofish] PW-MTOP url: %s", url)

        # Эмуляция действий пользователя перед запросом
        await self._random_mouse_move()
        await self._human_delay(200, 500)

        from playwright.async_api import Error as PWError

        try:
            raw = await asyncio.wait_for(
                self._page.evaluate(js_code),
                timeout=30.0,
            )
        except (PWError, TimeoutError, Exception) as exc:
            logger.error("[goofish] PW-MTOP evaluate error (proxy?): %s", exc)
            return {"ret": ["FAIL::PROXY_TIMEOUT_OR_DROP"]}

        if not isinstance(raw, dict):
            logger.error("PW-MTOP evaluate returned non-dict: %s", type(raw))
            return {"ret": ["FAIL::PROXY_TIMEOUT_OR_DROP"]}

        if not raw.get("ok"):
            error_msg = raw.get("error", "unknown")
            logger.error("PW-MTOP evaluate error: %s", error_msg)
            return {"ret": ["FAIL::PROXY_TIMEOUT_OR_DROP"]}

        try:
            response_data: dict[str, Any] = json.loads(raw["data"])
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error("PW-MTOP JSON decode error: %s", exc)
            raise

        ret = response_data.get("ret", [])
        ret_str = str(ret)

        if "RGV587_ERROR" in ret_str or "挤爆" in ret_str:
            logger.warning("PW-MTOP RGV587_ERROR on %s", api)
            # Даже через браузер блокируют — возможно, нужен логин
        elif "SUCCESS" in ret_str:
            # Синхронизируем куки после успешного запроса
            pass  # вызывающий забирает куки через get_cookies()

        return response_data

    # ── куки ───────────────────────────────────────────────

    async def get_cookies(self) -> dict[str, str]:
        """Возвращает актуальные куки из браузерного контекста."""
        if not self._context:
            return {}
        raw = await self._context.cookies()
        return {c["name"]: c["value"] for c in raw}

    # ── эмуляция пользователя ─────────────────────────────

    async def _human_delay(self, min_ms: float = 100, max_ms: float = 600) -> None:
        await asyncio.sleep(random.uniform(min_ms, max_ms) / 1000)

    async def _random_scroll(self) -> None:
        try:
            for _ in range(random.randint(1, 3)):
                x = random.randint(0, 300)
                y = random.randint(100, 700)
                await self._page.evaluate(f"window.scrollTo({x}, {y})")
                await self._human_delay(200, 800)
        except Exception:
            pass

    async def _random_mouse_move(self) -> None:
        try:
            for _ in range(random.randint(2, 5)):
                x = random.randint(100, 1800)
                y = random.randint(100, 900)
                await self._page.mouse.move(x, y, steps=random.randint(5, 15))
                await self._human_delay(50, 200)
        except Exception:
            pass

    # ── хелперы ────────────────────────────────────────────

    @staticmethod
    def _calc_sign(token: str, timestamp: str, data: str) -> str:
        raw = f"{token}&{timestamp}&{APP_KEY}&{data}"
        return hashlib.md5(raw.encode()).hexdigest()

    @staticmethod
    def _js_quote(value: str) -> str:
        """Экранирует строку для вставки в JavaScript."""
        return (
            value
            .replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
        )

    @staticmethod
    def _js_headers() -> str:
        return json.dumps({
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Origin": "https://www.goofish.com",
            "Referer": "https://www.goofish.com/",
        })

    # ── менеджер контекста ─────────────────────────────────

    async def __aenter__(self) -> "MtopPlaywrightClient":
        return self

    async def __aexit__(self, *args) -> None:
        await self.stop()


# ── тестовый запуск ────────────────────────────────────────

async def main() -> None:
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    item_id = sys.argv[1] if len(sys.argv) > 1 else "708353622311"
    logger.info("Testing MtopPlaywrightClient with item %s", item_id)

    async with MtopPlaywrightClient(headless=False) as client:
        result = await client.request(
            "mtop.taobao.idle.pc.detail",
            data={"itemId": item_id},
            version="1.0",
        )
        ret = result.get("ret", [])
        logger.info("ret: %s", ret)
        print(json.dumps(result, ensure_ascii=False, indent=2)[:1500])

        cookies = await client.get_cookies()
        logger.info("Browser cookies: %s", list(cookies.keys()))


if __name__ == "__main__":
    asyncio.run(main())
