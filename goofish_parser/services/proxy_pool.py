import asyncio
import logging
import time
from typing import Optional

import httpx
from telegram.error import NetworkError, TimedOut
from telegram.request import HTTPXRequest

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


class ProxyPool:
    def __init__(
        self,
        proxy_urls: list[str],
        bot_token: str,
        check_interval: int = 300,
        proxy_file: str = "",
    ):
        self._static_urls = proxy_urls
        self._token = bot_token
        self._check_interval = check_interval
        self._proxy_file = proxy_file
        self._working: list[tuple[str, float]] = []
        self._current_idx = 0
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None

    def _load_urls(self) -> list[str]:
        if self._proxy_file:
            try:
                urls = []
                with open(self._proxy_file, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            urls.append(line)
                if urls:
                    return urls
            except FileNotFoundError:
                pass
            except Exception as e:
                logger.warning("Failed to read proxy file %s: %s", self._proxy_file, e)
        return self._static_urls

    async def start(self):
        urls = self._load_urls()
        if not urls:
            logger.info("Proxy pool: no proxies configured")
            return
        await self._check_all()
        self._task = asyncio.create_task(self._periodic_check())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _check_all(self):
        urls = self._load_urls()
        if not urls:
            async with self._lock:
                self._working = []
                self._current_idx = 0
            return

        results = []
        timeout = httpx.Timeout(10, connect=5)
        async with httpx.AsyncClient(timeout=timeout) as client:
            for url in urls:
                start = time.monotonic()
                try:
                    resp = await client.get(
                        f"{url.rstrip('/')}/api/bot{self._token}/getMe"
                    )
                    if resp.status_code == 200:
                        latency = (time.monotonic() - start) * 1000
                        results.append((url, latency))
                except Exception:
                    pass

        results.sort(key=lambda x: x[1])
        async with self._lock:
            self._working = results
            self._current_idx = 0

        if results:
            logger.info(
                "Proxy pool: %d/%d working (best %.0fms)",
                len(results),
                len(urls),
                results[0][1],
            )
        elif urls:
            logger.warning("Proxy pool: all %d proxies dead", len(urls))

    async def _periodic_check(self):
        try:
            while True:
                await asyncio.sleep(self._check_interval)
                await self._check_all()
        except asyncio.CancelledError:
            pass

    async def get_current(self) -> Optional[str]:
        async with self._lock:
            if not self._working:
                return None
            return self._working[self._current_idx % len(self._working)][0]

    async def mark_failed(self):
        async with self._lock:
            if len(self._working) <= 1:
                return
            old = self._working[self._current_idx % len(self._working)][0]
            self._current_idx = (self._current_idx + 1) % len(self._working)
            new = self._working[self._current_idx % len(self._working)][0]
            if old != new:
                logger.warning("Proxy %s -> %s (failed)", old, new)


class ProxyPoolRequest(HTTPXRequest):
    def __init__(self, pool: ProxyPool, **kwargs):
        self._pool = pool
        super().__init__(**kwargs)

    async def do_request(self, url: str, method: str = "POST", **kwargs):
        current = await self._pool.get_current()
        if current:
            url = url.replace(
                TELEGRAM_API + "/", f"{current.rstrip('/')}/api/"
            )

        try:
            return await super().do_request(url, method=method, **kwargs)
        except (TimedOut, NetworkError):
            await self._pool.mark_failed()
            raise
