"""MtopClient — высокоскоростной движок запросов к MTOP API Goofish.

Использует curl_cffi с имперсонацией Chrome, MD5-подпись запросов
и куки из CookieManager (полученные через BrowserAuthenticator).

При получении RGV587_ERROR вызывает переданный колбэк refresh_session().
"""
import asyncio
import hashlib
import json
import logging
import random
import time
from typing import Any, Callable, Optional

from curl_cffi import BrowserType
from curl_cffi.requests import AsyncSession

from goofish_parser.config import H5_PROXIES, H5_DELAY_MIN, H5_DELAY_MAX

logger = logging.getLogger(__name__)

APP_KEY = "34839810"
MTOP_HOST = "https://h5api.m.goofish.com"

# Сигнатура колбэка обновления сессии
RefreshCallback = Callable[[], Any]


class MtopClient:
    """Асинхронный MTOP API клиент.

    Использует куки из переданного словаря, подписывает запросы MD5,
    умеет обновлять сессию через колбэк при RGV587_ERROR.
    """

    def __init__(
        self,
        cookies: Optional[dict[str, str]] = None,
        refresh_callback: Optional[RefreshCallback] = None,
        proxy: Optional[str] = None,
    ) -> None:
        self._cookies: dict[str, str] = cookies or {}
        self._token: str = self._extract_token()
        self._refresh_callback = refresh_callback
        self._proxy_url: Optional[str] = proxy
        self._session: Optional[AsyncSession] = None

    # ── управление куками ──────────────────────────────────

    def update_cookies(self, cookies: dict[str, str]) -> None:
        """Обновляет куки (после BrowserAuthenticator)."""
        self._cookies.update(cookies)
        self._token = self._extract_token()
        logger.info("Cookies updated, token=%s...", self._token[:12] if self._token else "?")

    def _extract_token(self) -> str:
        raw = self._cookies.get("_m_h5_tk", "")
        return raw.split("_")[0] if "_" in raw else ""

    def set_refresh_callback(self, cb: RefreshCallback) -> None:
        self._refresh_callback = cb

    # ── хелперы ────────────────────────────────────────────

    @staticmethod
    def _random_ua() -> str:
        return random.choice([
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/146.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/145.0.0.0 Safari/537.36",
        ])

    @staticmethod
    def _base_headers() -> dict[str, str]:
        ua = MtopClient._random_ua()
        return {
            "User-Agent": ua,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "sec-ch-ua": f'"Chromium";v="146", "Google Chrome";v="146", "Not.A/Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Origin": "https://www.goofish.com",
            "Referer": "https://www.goofish.com/",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def _cookie_str(self, ts: str) -> str:
        return "; ".join(f"{k}={v}" for k, v in self._cookies.items())

    def _pick_proxy(self) -> Optional[str]:
        return random.choice(H5_PROXIES) if H5_PROXIES else None

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            self._session = AsyncSession()
        return self._session

    @staticmethod
    def _calc_sign(token: str, timestamp: str, data: str) -> str:
        raw = f"{token}&{timestamp}&{APP_KEY}&{data}"
        return hashlib.md5(raw.encode()).hexdigest()

    @staticmethod
    async def jitter() -> None:
        delay = random.uniform(H5_DELAY_MIN, H5_DELAY_MAX)
        await asyncio.sleep(delay)

    # ── основной метод запроса ─────────────────────────────

    async def request(
        self,
        api: str,
        data: dict[str, Any] | str,
        *,
        version: str = "1.0",
        extra_params: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """Выполняет подписанный запрос к MTOP API.

        Args:
            api: Имя API (mtop.taobao.idle.pc.detail и т.п.)
            data: Тело запроса.
            version: Версия API.

        Returns:
            JSON-ответ от API.

        Raises:
            RuntimeError: Если нет токена даже после обновления сессии.
        """
        if not self._token:
            raise RuntimeError("No MTOP token — call refresh_session() first")

        timestamp = str(int(time.time() * 1000))
        data_str = data if isinstance(data, str) else json.dumps(data, separators=(",", ":"))
        sign = self._calc_sign(self._token, timestamp, data_str)

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

        url = f"{MTOP_HOST}/h5/{api}/{version}/"
        session = await self._get_session()
        proxy = self._proxy_url if self._proxy_url else self._pick_proxy()

        logger.debug("MTOP %s t=%s sign=%s", api, timestamp, sign[:12])

        resp = await session.post(
            url,
            params=params,
            data={"data": data_str},
            headers={
                **self._base_headers(),
                "Cookie": self._cookie_str(timestamp),
            },
            proxy=proxy,
            impersonate=BrowserType.chrome124,
            timeout=20,
        )

        result: dict[str, Any] = resp.json()
        ret = result.get("ret", [])
        ret_str = str(ret)

        if "RGV587_ERROR" in ret_str or "挤爆" in ret_str:
            logger.warning("RGV587_ERROR / anti-bot block for %s — refreshing session", api)

            if self._refresh_callback:
                await self._refresh_callback()
                return await self.request(api, data, version=version, extra_params=extra_params)

        if ret and isinstance(ret, list) and "FAIL" in ret[0]:
            logger.warning("MTOP error: %s — api=%s", ret[0], api)

        return result

    # ── публичные API ──────────────────────────────────────

    async def get_item_detail(self, item_id: str) -> dict[str, Any]:
        return await self.request(
            "mtop.taobao.idle.pc.detail",
            data={"itemId": item_id},
            version="1.0",
        )

    async def search_items(
        self,
        keyword: str,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        return await self.request(
            "mtop.taobao.idlemtopsearch.search",
            data={
                "keyword": keyword,
                "page": page,
                "pageSize": page_size,
                "searchFrom": "h5",
            },
            version="1.0",
        )

    # ── close ──────────────────────────────────────────────

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> "MtopClient":
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()
