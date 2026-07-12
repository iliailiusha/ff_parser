import asyncio
import logging
import random
from typing import Optional

import aiohttp

from goofish_parser.config import (
    H5_PROXIES,
    H5_PROXY_ROTATION,
    H5_DELAY_MIN,
    H5_DELAY_MAX,
    H5_MAX_RETRIES,
    H5_TIMEOUT,
    MOBILE_USER_AGENTS,
)

logger = logging.getLogger(__name__)


class H5Client:
    """Асинхронный HTTP-клиент для H5-страниц Goofish.

    Особенности:
      - Ротация мобильных User-Agent
      - Ротация прокси (roundrobin / random)
      - Ретри с увеличением задержки при 403 / 429
      - Случайная задержка (jitter) между запросами
      - Автоматический follow redirects (Alibaba)
    """

    def __init__(self) -> None:
        self._proxy_index = 0
        self._proxies = H5_PROXIES[:]
        self._proxy_rotation = H5_PROXY_ROTATION
        self._max_retries = H5_MAX_RETRIES
        self._timeout = H5_TIMEOUT
        self._delay_min = H5_DELAY_MIN
        self._delay_max = H5_DELAY_MAX

        self._session: Optional[aiohttp.ClientSession] = None

    # ── public helpers ──────────────────────────────────────

    @staticmethod
    def random_ua() -> str:
        return random.choice(MOBILE_USER_AGENTS)

    def next_proxy(self) -> Optional[str]:
        if not self._proxies:
            return None
        if self._proxy_rotation == "random":
            return random.choice(self._proxies)
        proxy = self._proxies[self._proxy_index % len(self._proxies)]
        self._proxy_index += 1
        return proxy

    @staticmethod
    async def jitter(min_s: float = 1.0, max_s: float = 3.0) -> None:
        delay = random.uniform(min_s, max_s)
        logger.debug("jitter %.2fs", delay)
        await asyncio.sleep(delay)

    # ── session management ──────────────────────────────────

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self._timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ── main fetch method ───────────────────────────────────

    async def fetch(
        self,
        url: str,
        *,
        headers: Optional[dict[str, str]] = None,
        max_retries: Optional[int] = None,
    ) -> Optional[str]:
        session = await self._ensure_session()
        retries = max_retries if max_retries is not None else self._max_retries
        last_exc: Optional[Exception] = None

        for attempt in range(1, retries + 2):
            request_headers = {
                "User-Agent": self.random_ua(),
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;"
                    "q=0.9,image/avif,image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "DNT": "1",
                "Upgrade-Insecure-Requests": "1",
            }
            if headers:
                request_headers.update(headers)

            proxy = self.next_proxy()
            proxy_arg = proxy if proxy else None

            try:
                async with session.get(
                    url,
                    headers=request_headers,
                    proxy=proxy_arg,
                    allow_redirects=True,
                    ssl=False,
                ) as resp:
                    status = resp.status
                    logger.info(
                        "GET %s — %s (attempt %d/%d%s)",
                        url, status, attempt, retries + 1,
                        f", proxy={proxy}" if proxy else "",
                    )

                    if status == 200:
                        return await resp.text()

                    if status in (403, 429):
                        logger.warning(
                            "HTTP %d — retrying (attempt %d/%d)",
                            status, attempt, retries + 1,
                        )
                        if attempt <= retries:
                            backoff = 2 ** attempt + random.uniform(0, 1)
                            await asyncio.sleep(backoff)
                            continue
                        return None

                    if status in (301, 302, 303, 307, 308):
                        final_url = str(resp.url)
                        if final_url != url:
                            logger.info("Redirected → %s", final_url)
                            return await self.fetch(
                                final_url,
                                headers=headers,
                                max_retries=retries - attempt + 1,
                            )
                        return None

                    logger.error("HTTP %d for %s", status, url)
                    return None

            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_exc = exc
                logger.warning(
                    "Request failed (%s), attempt %d/%d",
                    exc, attempt, retries + 1,
                )
                if attempt <= retries:
                    await asyncio.sleep(2 ** attempt)
                    continue
                break

        logger.error("All retries exhausted for %s: %s", url, last_exc)
        return None

    # ── context manager ─────────────────────────────────────

    async def __aenter__(self) -> "H5Client":
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()
