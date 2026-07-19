import asyncio
import json
import logging
import os
import time
from typing import Any, Optional, List

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None

logger = logging.getLogger(__name__)


class InMemoryCache:
    """Fallback in-memory cache with TTL support."""

    def __init__(self, default_ttl: int = 300, key_prefix: str = "ff_parser:"):
        self.default_ttl = default_ttl
        self.key_prefix = key_prefix
        self._data: dict[str, tuple[Any, float]] = {}
        self._lock = asyncio.Lock()

    def _make_key(self, key: str) -> str:
        return f"{self.key_prefix}{key}"

    def _is_expired(self, expires_at: float) -> bool:
        return time.time() > expires_at

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            full_key = self._make_key(key)
            if full_key in self._data:
                value, expires_at = self._data[full_key]
                if not self._is_expired(expires_at):
                    return value
                del self._data[full_key]
        return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        async with self._lock:
            expires_at = time.time() + (ttl or self.default_ttl)
            self._data[self._make_key(key)] = (value, expires_at)
        return True

    async def delete(self, key: str) -> bool:
        async with self._lock:
            self._data.pop(self._make_key(key), None)
        return True

    async def exists(self, key: str) -> bool:
        return await self.get(key) is not None

    async def mget(self, keys: List[str]) -> List[Optional[Any]]:
        return [await self.get(k) for k in keys]

    async def mset(self, mapping: dict[str, Any], ttl: Optional[int] = None) -> bool:
        for k, v in mapping.items():
            await self.set(k, v, ttl)
        return True

    async def close(self):
        self._data.clear()


class RedisCache:
    def __init__(
        self,
        url: Optional[str] = None,
        default_ttl: int = 300,
        key_prefix: str = "ff_parser:",
        max_connections: int = 20,
    ):
        self.url = url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.default_ttl = default_ttl
        self.key_prefix = key_prefix
        self.max_connections = max_connections
        self._client: Optional[redis.Redis] = None
        self._pool: Optional[redis.ConnectionPool] = None
        self._lock = asyncio.Lock()

    async def _get_pool(self) -> redis.ConnectionPool:
        if self._pool is None:
            async with self._lock:
                if self._pool is None:
                    self._pool = redis.ConnectionPool.from_url(
                        self.url,
                        max_connections=self.max_connections,
                        decode_responses=True,
                    )
        return self._pool

    async def _get_client(self) -> redis.Redis:
        if self._client is None:
            pool = await self._get_pool()
            self._client = redis.Redis(connection_pool=pool)
        return self._client

    def _make_key(self, key: str) -> str:
        return f"{self.key_prefix}{key}"

    async def get(self, key: str) -> Optional[Any]:
        try:
            client = await self._get_client()
            data = await client.get(self._make_key(key))
            if data:
                return json.loads(data)
        except Exception as e:
            logger.warning(f"Redis GET error for {key}: {e}")
        return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        try:
            client = await self._get_client()
            data = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            await client.setex(self._make_key(key), ttl or self.default_ttl, data)
            return True
        except Exception as e:
            logger.warning(f"Redis SET error for {key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        try:
            client = await self._get_client()
            await client.delete(self._make_key(key))
            return True
        except Exception as e:
            logger.warning(f"Redis DELETE error for {key}: {e}")
            return False

    async def exists(self, key: str) -> bool:
        try:
            client = await self._get_client()
            return await client.exists(self._make_key(key)) > 0
        except Exception:
            return False

    async def mget(self, keys: List[str]) -> List[Optional[Any]]:
        try:
            client = await self._get_client()
            prefixed = [self._make_key(k) for k in keys]
            data = await client.mget(prefixed)
            return [json.loads(d) if d else None for d in data]
        except Exception as e:
            logger.warning(f"Redis MGET error: {e}")
            return [None] * len(keys)

    async def mset(self, mapping: dict[str, Any], ttl: Optional[int] = None) -> bool:
        try:
            client = await self._get_client()
            prefixed = {self._make_key(k): json.dumps(v, ensure_ascii=False, separators=(",", ":"))
                        for k, v in mapping.items()}
            pipe = client.pipeline()
            for k, v in prefixed.items():
                pipe.setex(k, ttl or self.default_ttl, v)
            await pipe.execute()
            return True
        except Exception as e:
            logger.warning(f"Redis MSET error: {e}")
            return False

    async def close(self):
        if self._client:
            await self._client.close()
            self._client = None
        if self._pool:
            await self._pool.disconnect()
            self._pool = None


_cache: Optional[Any] = None


def get_cache() -> Any:
    global _cache
    if _cache is None:
        if REDIS_AVAILABLE:
            try:
                _cache = RedisCache()
                logger.info("Using Redis cache")
            except Exception as e:
                logger.warning(f"Redis unavailable, falling back to in-memory cache: {e}")
                _cache = InMemoryCache()
        else:
            logger.info("Redis not installed, using in-memory cache")
            _cache = InMemoryCache()
    return _cache


async def close_cache():
    global _cache
    if _cache:
        await _cache.close()
        _cache = None


async def init_cache(url: Optional[str] = None, default_ttl: int = 300) -> Any:
    """Initialize cache (for backward compatibility). Just calls get_cache()."""
    return get_cache()


def make_search_cache_key(
    query: str,
    platforms: List[str],
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    price_currency: str = "KRW",
) -> str:
    parts = [
        "search",
        query.lower().strip(),
        ",".join(sorted(platforms)),
        f"pmin:{price_min or 0}",
        f"pmax:{price_max or 0}",
        f"curr:{price_currency}",
    ]
    return "|".join(parts)