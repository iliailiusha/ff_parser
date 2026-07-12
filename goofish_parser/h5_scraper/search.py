"""search_by_brand_type — точка входа для интеграции Goofish в мультипоиск бота.

Контракт: async def search_by_brand_type(brand, item_type, price_min, price_max, limit)
→ SearchResult(items=list[GoofishItem]).

Fast Path: MtopClient (curl_cffi).
Safe Path: MtopPlaywrightClient (page.evaluate) при RGV587.
"""
import asyncio
import logging
from typing import Any, Optional

from goofish_parser.h5_scraper.cookie_manager import CookieManager
from goofish_parser.h5_scraper.mtop_client import MtopClient
from goofish_parser.h5_scraper.mtop_playwright_client import MtopPlaywrightClient
from goofish_parser.scraper.models import GoofishItem, SearchResult

logger = logging.getLogger(__name__)

_client: Optional[MtopClient] = None
_pw_client: Optional[MtopPlaywrightClient] = None
_init_lock = asyncio.Lock()


def _parse_item(raw: dict[str, Any], source: str = "goofish") -> Optional[GoofishItem]:
    """Преобразует один элемент из ответа MTOP API в GoofishItem."""
    item_id = str(raw.get("itemId") or "")
    if not item_id:
        return None

    title = raw.get("title") or raw.get("itemTitle") or ""
    sold_price = raw.get("soldPrice") or raw.get("price") or "0"
    try:
        price_cny = float(sold_price)
    except (ValueError, TypeError):
        price_cny = 0.0

    original_price = raw.get("originalPrice") or raw.get("priceOriginal") or ""
    price_original_cny = 0.0
    try:
        price_original_cny = float(original_price) if original_price else 0.0
    except (ValueError, TypeError):
        pass

    images_raw = raw.get("images") or raw.get("image") or []
    if isinstance(images_raw, str):
        images = [images_raw]
    elif isinstance(images_raw, list):
        images = [img for img in images_raw if img]
    else:
        images = []

    item_url = raw.get("itemUrl") or raw.get("url") or ""
    if item_url and not item_url.startswith("http"):
        item_url = f"https://www.goofish.com/item?id={item_id}"

    seller_id = str(raw.get("sellerId") or raw.get("seller_id") or "")

    created_at = raw.get("createdAt") or raw.get("gmtCreate") or raw.get("pubTs") or ""

    location = raw.get("location") or raw.get("city") or raw.get("province") or ""

    return GoofishItem(
        item_id=item_id,
        title=title,
        price_cny=price_cny,
        url=item_url,
        images=images,
        seller_id=seller_id,
        price_original_cny=price_original_cny,
        location=location,
        created_at=created_at,
    )


async def _ensure_client() -> MtopClient:
    """Ленивая инициализация MtopClient с куками."""
    global _client
    if _client is not None:
        return _client
    async with _init_lock:
        if _client is not None:
            return _client
        cm = CookieManager()
        cookies = cm.load()
        if not cm.is_valid(cookies):
            from goofish_parser.h5_scraper.browser_auth import BrowserAuthenticator
            logger.info("[GOOFISH] No valid session, running BrowserAuthenticator...")
            auth = BrowserAuthenticator(headless=True)
            cookies = await asyncio.wait_for(
                auth.get_cookies(),
                timeout=45.0,
            )
            cm.save(cookies)
        _client = MtopClient(cookies=cookies)
        return _client


async def _ensure_pw_client() -> MtopPlaywrightClient:
    """Ленивая инициализация Safe Path клиента."""
    global _pw_client
    if _pw_client is not None:
        return _pw_client
    async with _init_lock:
        if _pw_client is not None:
            return _pw_client
        _pw_client = MtopPlaywrightClient(headless=True)
        return _pw_client


async def search_by_brand_type(
    brand: str,
    item_type: str = "",
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    limit: int = 50,
) -> SearchResult:
    """Поиск на Goofish по бренду/ключевому слову.

    Args:
        brand: Поисковый запрос / бренд.
        item_type: Тип товара (не используется для Goofish — поиск по ключевым словам).
        price_min: Мин. цена в юанях (CNY).
        price_max: Макс. цена в юанях (CNY).
        limit: Лимит результатов.

    Returns:
        SearchResult со списком GoofishItem.
    """
    query = f"{brand} {item_type}".strip() if item_type else brand

    try:
        return await asyncio.wait_for(
            _search(query, brand, item_type, price_min, price_max, limit),
            timeout=90.0,
        )
    except asyncio.TimeoutError:
        logger.warning("[GOOFISH] Search timed out for '%s' (90s)", query)
        return SearchResult(items=[], error="Goofish search timed out", empty=True)


async def _search(
    query: str,
    brand: str,
    item_type: str,
    price_min: Optional[float],
    price_max: Optional[float],
    limit: int,
) -> SearchResult:
    try:
        client = await _ensure_client()

        payload: dict[str, Any] = {
            "keyword": query,
            "pageNumber": 1,
            "pageSize": min(limit, 100),
            "sort": "realtime",
            "searchFrom": "h5",
        }
        if price_min is not None:
            payload["priceMin"] = int(price_min * 100)
        if price_max is not None:
            payload["priceMax"] = int(price_max * 100)

        # Fast Path
        result = await client.request(
            "mtop.taobao.idlemtopsearch.search",
            data=payload,
            version="1.0",
        )

        ret = result.get("ret", [])
        ret_str = str(ret)

        if "RGV587_ERROR" in ret_str or "挤爆" in ret_str:
            logger.info("[GOOFISH] RGV587 on '%s' — switching to Safe Path", query)
            pw = await _ensure_pw_client()
            result = await pw.request(
                "mtop.taobao.idlemtopsearch.search",
                data=payload,
                version="1.0",
            )
            if result:
                # Sync cookies after Safe Path success
                cookies = await pw.get_cookies()
                if cookies:
                    cm = CookieManager()
                    cm.save(cookies)
                    client.update_cookies(cookies)

        items_raw = _extract_items(result)
        if not items_raw:
            return SearchResult(items=[], empty=True)

        items = []
        for raw in items_raw[:limit]:
            parsed = _parse_item(raw)
            if parsed:
                items.append(parsed)

        logger.info(
            "[GOOFISH] '%s': found %d items (raw=%d)",
            query,
            len(items),
            len(items_raw),
        )
        return SearchResult(items=items, empty=not bool(items))

    except Exception as exc:
        logger.error("[GOOFISH] Search error for '%s': %s", query, exc)
        return SearchResult(items=[], error=str(exc), empty=True)


def _extract_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Извлекает список товаров из ответа MTOP API."""
    if not result or not isinstance(result, dict):
        return []
    data = result.get("data")
    if not data or not isinstance(data, dict):
        return []
    items = data.get("items") or data.get("itemList") or []
    if isinstance(items, list):
        return items
    return []


async def close() -> None:
    """Закрывает клиенты (вызвать при завершении работы бота)."""
    global _client, _pw_client
    if _client:
        await _client.close()
        _client = None
    if _pw_client:
        await _pw_client.stop()
        _pw_client = None
