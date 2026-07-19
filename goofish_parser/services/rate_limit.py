import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Dict

logger = logging.getLogger(__name__)


@dataclass
class TokenBucket:
    rate: float
    burst: int
    _tokens: float = field(default=0, init=False)
    _last_update: float = field(default=0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self):
        self._tokens = float(self.burst)
        self._last_update = time.monotonic()

    async def take(self, tokens: int = 1) -> bool:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_update
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
            self._last_update = now

            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    async def wait_for(self, tokens: int = 1) -> float:
        while True:
            if await self.take(tokens):
                return 0.0
            async with self._lock:
                needed = tokens - self._tokens
                wait_time = needed / self.rate
            await asyncio.sleep(min(wait_time, 0.5))


class RateLimiter:
    def __init__(
        self,
        default_rate: float = 1.0,
        default_burst: int = 3,
        cleanup_interval: int = 300,
    ):
        self.default_rate = default_rate
        self.default_burst = default_burst
        self.buckets: Dict[int, TokenBucket] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self.cleanup_interval = cleanup_interval

    def _get_bucket(self, user_id: int, rate: Optional[float] = None, burst: Optional[int] = None) -> TokenBucket:
        if user_id not in self.buckets:
            self.buckets[user_id] = TokenBucket(
                rate=rate or self.default_rate,
                burst=burst or self.default_burst,
            )
        return self.buckets[user_id]

    async def check_limit(
        self,
        user_id: int,
        tokens: int = 1,
        rate: Optional[float] = None,
        burst: Optional[int] = None,
    ) -> bool:
        bucket = self._get_bucket(user_id, rate, burst)
        return await bucket.take(tokens)

    async def wait_for_limit(
        self,
        user_id: int,
        tokens: int = 1,
        rate: Optional[float] = None,
        burst: Optional[int] = None,
    ) -> float:
        bucket = self._get_bucket(user_id, rate, burst)
        return await bucket.wait_for(tokens)

    def set_user_limits(self, user_id: int, rate: float, burst: int):
        self.buckets[user_id] = TokenBucket(rate=rate, burst=burst)

    async def cleanup(self):
        now = time.monotonic()
        to_remove = []
        for user_id, bucket in self.buckets.items():
            if now - bucket._last_update > self.cleanup_interval:
                to_remove.append(user_id)
        for uid in to_remove:
            del self.buckets[uid]

    async def start_cleanup_task(self):
        async def _cleanup():
            while True:
                await asyncio.sleep(self.cleanup_interval)
                await self.cleanup()
        self._cleanup_task = asyncio.create_task(_cleanup())

    async def stop_cleanup_task(self):
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass


class SlidingWindowLog:
    def __init__(self, window_seconds: float, max_requests: int):
        self.window = window_seconds
        self.max_requests = max_requests
        self._logs: Dict[int, list[float]] = {}
        self._lock = asyncio.Lock()

    async def check(self, user_id: int) -> bool:
        now = time.monotonic()
        async with self._lock:
            if user_id not in self._logs:
                self._logs[user_id] = []
            logs = self._logs[user_id]
            cutoff = now - self.window
            while logs and logs[0] < cutoff:
                logs.pop(0)
            if len(logs) < self.max_requests:
                logs.append(now)
                return True
            return False

    async def wait_time(self, user_id: int) -> float:
        now = time.monotonic()
        async with self._lock:
            logs = self._logs.get(user_id, [])
            if len(logs) < self.max_requests:
                return 0.0
            cutoff = now - self.window
            while logs and logs[0] < cutoff:
                logs.pop(0)
            if len(logs) < self.max_requests:
                return 0.0
            return logs[0] + self.window - now


_rate_limiter: Optional[RateLimiter] = None
_search_limiter: Optional[SlidingWindowLog] = None


def get_rate_limiter() -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


def get_search_limiter() -> SlidingWindowLog:
    global _search_limiter
    if _search_limiter is None:
        _search_limiter = SlidingWindowLog(window_seconds=60, max_requests=10)
    return _search_limiter


async def init_rate_limiters(
    default_rate: float = 1.0,
    default_burst: int = 3,
    search_window: int = 60,
    search_max: int = 10,
):
    global _rate_limiter, _search_limiter
    _rate_limiter = RateLimiter(default_rate=default_rate, default_burst=default_burst)
    _search_limiter = SlidingWindowLog(window_seconds=search_window, max_requests=search_max)
    await _rate_limiter.start_cleanup_task()


async def close_rate_limiters():
    global _rate_limiter
    if _rate_limiter:
        await _rate_limiter.stop_cleanup_task()
        _rate_limiter = None