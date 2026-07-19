import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Awaitable, Optional, TypeVar

from goofish_parser.scraper.models import GoofishItem, SearchResult

logger = logging.getLogger(__name__)

T = TypeVar("T")


class PlatformErrorType(Enum):
    RATE_LIMITED = "rate_limited"
    CAPTCHA = "captcha"
    AUTH_REQUIRED = "auth_required"
    PARSING_FAILED = "parsing_failed"
    NETWORK_ERROR = "network_error"
    UNKNOWN = "unknown"


@dataclass
class ParserResult:
    items: list[GoofishItem]
    error: Optional[PlatformErrorType] = None
    error_msg: str = ""
    platform: str = ""
    fallback_used: bool = False


class CircuitBreakerOpenError(Exception):
    pass


@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    success_threshold: int = 2

    _state: str = "closed"
    _failures: int = 0
    _successes: int = 0
    _last_failure: float = 0
    _lock: asyncio.Lock = None

    def __post_init__(self):
        self._lock = asyncio.Lock()

    async def call(self, func: Callable[..., Awaitable[T]], *args, **kwargs) -> T:
        async with self._lock:
            if self._state == "open":
                if time.monotonic() - self._last_failure >= self.recovery_timeout:
                    self._state = "half_open"
                    self._successes = 0
                    logger.info(f"Circuit breaker [{self.name}] -> HALF_OPEN")
                else:
                    raise CircuitBreakerOpenError(f"Circuit breaker [{self.name}] is OPEN")

        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure()
            raise

    async def _on_success(self):
        async with self._lock:
            if self._state == "half_open":
                self._successes += 1
                if self._successes >= self.success_threshold:
                    self._state = "closed"
                    self._failures = 0
                    logger.info(f"Circuit breaker [{self.name}] -> CLOSED")
            elif self._state == "closed":
                self._failures = 0

    async def _on_failure(self):
        async with self._lock:
            self._failures += 1
            self._last_failure = time.monotonic()
            if self._state == "half_open":
                self._state = "open"
                logger.warning(f"Circuit breaker [{self.name}] -> OPEN (half-open failure)")
            elif self._failures >= self.failure_threshold:
                self._state = "open"
                logger.warning(f"Circuit breaker [{self.name}] -> OPEN (threshold reached)")

    def get_state(self) -> dict:
        return {
            "name": self.name,
            "state": self._state,
            "failures": self._failures,
            "successes": self._successes,
        }


class ResilientParser:
    def __init__(
        self,
        platform: str,
        primary: Callable[..., Awaitable[ParserResult]],
        fallbacks: list[Callable[..., Awaitable[ParserResult]]] = None,
        max_retries: int = 3,
        base_delay: float = 1.0,
        circuit_breaker_config: dict = None,
    ):
        self.platform = platform
        self.primary = primary
        self.fallbacks = fallbacks or []
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.circuit_breaker = CircuitBreaker(
            name=platform,
            **(circuit_breaker_config or {}),
        )

    async def search(self, *args, **kwargs) -> ParserResult:
        if self.circuit_breaker._state == "open":
            logger.warning(f"[{self.platform}] Circuit OPEN, skipping")
            return ParserResult(
                items=[],
                error=PlatformErrorType.UNKNOWN,
                error_msg="Circuit breaker open",
                platform=self.platform,
            )

        # Primary with retries
        for attempt in range(self.max_retries):
            try:
                result = await asyncio.wait_for(
                    self.primary(*args, **kwargs),
                    timeout=90.0,
                )
                if not result.error:
                    return result
                if result.error in (PlatformErrorType.RATE_LIMITED, PlatformErrorType.CAPTCHA):
                    break
            except asyncio.TimeoutError:
                logger.warning(f"[{self.platform}] Timeout attempt {attempt+1}/{self.max_retries}")
            except Exception as e:
                logger.error(f"[{self.platform}] Error attempt {attempt+1}: {e}")

            if attempt < self.max_retries - 1:
                await asyncio.sleep(self.base_delay * (2 ** attempt))

        # Fallbacks
        for i, fallback in enumerate(self.fallbacks):
            try:
                logger.info(f"[{self.platform}] Trying fallback #{i+1}")
                result = await asyncio.wait_for(fallback(*args, **kwargs), timeout=120.0)
                if not result.error:
                    result.fallback_used = True
                    return result
            except Exception as e:
                logger.error(f"[{self.platform}] Fallback #{i+1} failed: {e}")

        return ParserResult(
            items=[],
            error=PlatformErrorType.UNKNOWN,
            error_msg="All strategies exhausted",
            platform=self.platform,
        )


class ParserRegistry:
    def __init__(self):
        self._parsers: dict[str, ResilientParser] = {}

    def register(self, platform: str, parser: ResilientParser):
        self._parsers[platform] = parser

    def get(self, platform: str) -> Optional[ResilientParser]:
        return self._parsers.get(platform)

    async def search_all(
        self,
        platforms: list[str],
        *args,
        **kwargs
    ) -> dict[str, ParserResult]:
        tasks = {}
        for p in platforms:
            parser = self._parsers.get(p)
            if parser:
                tasks[p] = asyncio.create_task(parser.search(*args, **kwargs))

        results = {}
        for p, task in tasks.items():
            try:
                results[p] = await task
            except Exception as e:
                logger.error(f"[{p}] Search task failed: {e}")
                results[p] = ParserResult(
                    items=[],
                    error=PlatformErrorType.UNKNOWN,
                    error_msg=str(e),
                    platform=p,
                )
        return results

    def get_states(self) -> list[dict]:
        return [p.circuit_breaker.get_state() for p in self._parsers.values()]


_parser_registry: Optional[ParserRegistry] = None


def get_parser_registry() -> ParserRegistry:
    global _parser_registry
    if _parser_registry is None:
        _parser_registry = ParserRegistry()
    return _parser_registry


async def init_parser_registry() -> ParserRegistry:
    registry = get_parser_registry()

    from goofish_parser.ff_scraper.search import search_by_brand_type as ff_search
    from goofish_parser.bunjang_scraper.search import search_by_brand_type as bunjang_search
    from goofish_parser.carousell_scraper.search import search_by_brand_type as carousell_search
    from goofish_parser.mercari_jp_scraper.search import search_by_brand_type as mercari_jp_search
    from goofish_parser.h5_scraper.search import search_by_brand_type as goofish_search
    from goofish_parser.services.multi_search import PLATFORM_CURRENCY, PLATFORM_LANG, _translate_type
    from goofish_parser.services.exchange_rate import get_krw_to_rub, get_jpy_to_rub, get_sgd_to_rub, get_cny_to_rub

    def _convert_price(price: Optional[float], from_curr: str, to_curr: str) -> Optional[float]:
        if price is None or from_curr == to_curr:
            return price
        rates = {
            ("KRW", "JPY"): lambda: get_krw_to_rub() / get_jpy_to_rub(),
            ("KRW", "SGD"): lambda: get_krw_to_rub() / get_sgd_to_rub(),
            ("KRW", "CNY"): lambda: get_krw_to_rub() / get_cny_to_rub(),
            ("RUB", "KRW"): lambda: price / get_krw_to_rub() if get_krw_to_rub() else price,
            ("RUB", "JPY"): lambda: price / get_jpy_to_rub() if get_jpy_to_rub() else price,
            ("RUB", "SGD"): lambda: price / get_sgd_to_rub() if get_sgd_to_rub() else price,
            ("RUB", "CNY"): lambda: price / get_cny_to_rub() if get_cny_to_rub() else price,
        }
        key = (from_curr, to_curr)
        if key in rates:
            try:
                return rates[key]()
            except Exception:
                pass
        return price

    async def _wrap_search(search_func, platform: str):
        async def _inner(
            brand: str,
            item_type_ru: str,
            user_id: int,
            model: str = "",
            price_min: Optional[float] = None,
            price_max: Optional[float] = None,
            price_currency: str = "KRW",
            limit: int = 50,
        ) -> ParserResult:
            try:
                plat_curr = PLATFORM_CURRENCY.get(platform, "KRW")
                plat_price_min = _convert_price(price_min, price_currency, plat_curr)
                plat_price_max = _convert_price(price_max, price_currency, plat_curr)

                queries = [_translate_type(item_type_ru, PLATFORM_LANG.get(platform, "en"))]
                if model:
                    queries.append(f"{queries[0]} {model}".strip())

                all_items = []
                for q in queries:
                    result = await search_func(
                        brand=brand,
                        item_type=q,
                        price_min=plat_price_min,
                        price_max=plat_price_max,
                        limit=limit,
                    )
                    if result and result.items:
                        all_items.extend(result.items)

                return ParserResult(items=all_items, platform=platform)
            except Exception as e:
                err_msg = str(e).lower()
                if "429" in err_msg or "rate limit" in err_msg or "too many" in err_msg:
                    return ParserResult(items=[], error=PlatformErrorType.RATE_LIMITED, error_msg=str(e), platform=platform)
                if "403" in err_msg or "forbidden" in err_msg:
                    return ParserResult(items=[], error=PlatformErrorType.RATE_LIMITED, error_msg=str(e), platform=platform)
                if "captcha" in err_msg or "challenge" in err_msg:
                    return ParserResult(items=[], error=PlatformErrorType.CAPTCHA, error_msg=str(e), platform=platform)
                if "401" in err_msg or "unauthorized" in err_msg or "auth" in err_msg:
                    return ParserResult(items=[], error=PlatformErrorType.AUTH_REQUIRED, error_msg=str(e), platform=platform)
                return ParserResult(items=[], error=PlatformErrorType.UNKNOWN, error_msg=str(e), platform=platform)
        return _inner

    ff_wrapped = await _wrap_search(ff_search, "fruitsfamily")
    bunjang_wrapped = await _wrap_search(bunjang_search, "bunjang")
    carousell_wrapped = await _wrap_search(carousell_search, "carousell")
    mercari_wrapped = await _wrap_search(mercari_jp_search, "mercari_jp")
    goofish_wrapped = await _wrap_search(goofish_search, "goofish")

    registry.register("fruitsfamily", ResilientParser("fruitsfamily", ff_wrapped))
    registry.register("bunjang", ResilientParser("bunjang", bunjang_wrapped))
    registry.register("carousell", ResilientParser("carousell", carousell_wrapped))
    registry.register("mercari_jp", ResilientParser("mercari_jp", mercari_wrapped))
    registry.register("goofish", ResilientParser("goofish", goofish_wrapped))

    return registry