import asyncio
import logging
from typing import Optional

from goofish_parser.scraper.models import GoofishItem, PLATFORM_INFO, ALL_PLATFORMS, COUNTRY_PLATFORMS
from goofish_parser.storage.db import get_enabled_platforms
from goofish_parser.services.exchange_rate import get_krw_to_rub, get_jpy_to_rub, get_sgd_to_rub, get_cny_to_rub
from goofish_parser.services.cache import get_cache, make_search_cache_key
from goofish_parser.services.smart_search import get_smart_search

logger = logging.getLogger(__name__)


PLATFORM_LANG: dict[str, str] = {
    "fruitsfamily": "ko",
    "bunjang": "ko",
    "carousell": "en",
    "mercari_jp": "ja",
    "goofish": "zh",
}

PLATFORM_CURRENCY: dict[str, str] = {
    "fruitsfamily": "KRW",
    "bunjang": "KRW",
    "carousell": "SGD",
    "mercari_jp": "JPY",
    "goofish": "CNY",
}

PLATFORM_SEARCHERS: dict[str, str] = {
    "fruitsfamily": "goofish_parser.ff_scraper.search",
    "bunjang": "goofish_parser.bunjang_scraper.search",
    "carousell": "goofish_parser.carousell_scraper.search",
    "mercari_jp": "goofish_parser.mercari_jp_scraper.search",
    "goofish": "goofish_parser.h5_scraper.search",
}

from goofish_parser.bot.translation import CLOTHING_RU_TO_KO

CLOTHING_EN: dict[str, str] = {
    "кроссовки": "sneakers",
    "кеды": "sneakers",
    "ботинки": "boots",
    "сапоги": "boots",
    "футболка": "t-shirt",
    "рубашка": "shirt",
    "свитер": "sweater",
    "свитшот": "sweatshirt",
    "толстовка": "sweatshirt",
    "худи": "hoodie",
    "куртка": "jacket",
    "пуховик": "puffer",
    "пальто": "coat",
    "ветровка": "windbreaker",
    "джинсы": "jeans",
    "штаны": "pants",
    "брюки": "trousers",
    "шорты": "shorts",
    "платье": "dress",
    "костюм": "suit",
    "пиджак": "blazer",
    "жилетка": "vest",
    "лонгслив": "longsleeve",
    "майка": "tank top",
    "спортивный костюм": "tracksuit",
    "бомбер": "bomber",
    "косуха": "leather jacket",
    "джинсовка": "denim jacket",
    "карго": "cargo pants",
    "джоггеры": "joggers",
    "треники": "sweatpants",
    "легинсы": "leggings",
    "шапка": "hat",
    "кепка": "cap",
    "рюкзак": "backpack",
    "сумка": "bag",
    "ремень": "belt",
    "носки": "socks",
    "шарф": "scarf",
    "перчатки": "gloves",
    "часы": "watch",
    "очки": "glasses",
    "браслет": "bracelet",
    "кольцо": "ring",
    "серьги": "earrings",
    "купальник": "swimsuit",
    "плавки": "swim trunks",
    "трусы": "underwear",
    "колготки": "tights",
    "сланцы": "slides",
    "тапки": "slippers",
    "панама": "bucket hat",
    "бейсболка": "cap",
    "флиска": "fleece",
}


# Build EN→KO mapping from existing RU→KO and RU→EN dicts
_EN_TO_KO: dict[str, str] = {}
for _ru, _ko in CLOTHING_RU_TO_KO.items():
    _en = CLOTHING_EN.get(_ru)
    if _en:
        _EN_TO_KO[_en] = _ko


def translate_model(model: str) -> list[str]:
    ml = model.lower().strip()
    variants = {ml}
    ko = _EN_TO_KO.get(ml)
    if ko:
        variants.add(ko)
    ko = CLOTHING_RU_TO_KO.get(ml)
    if ko:
        variants.add(ko)
    return list(variants)


def _translate_type(item_type: str, lang: str) -> str:
    if not item_type:
        return ""
    if lang == "ko":
        return CLOTHING_RU_TO_KO.get(item_type, item_type)
    if lang == "ja":
        return CLOTHING_EN.get(item_type, item_type)
    return CLOTHING_EN.get(item_type, item_type)


def _deduplicate(items: list[GoofishItem]) -> list[GoofishItem]:
    seen: set[str] = set()
    result: list[GoofishItem] = []
    for item in items:
        key = f"{item.source}:{item.item_id}"
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _convert_price(price: Optional[float], from_currency: str, to_currency: str) -> Optional[float]:
    if price is None or from_currency == to_currency:
        return price
    if from_currency == "RUB" and to_currency == "KRW":
        rate = get_krw_to_rub()
        return round(price / rate) if rate else price
    if from_currency == "RUB" and to_currency == "JPY":
        rate = get_jpy_to_rub()
        return round(price / rate) if rate else price
    if from_currency == "RUB" and to_currency == "SGD":
        rate = get_sgd_to_rub()
        return round(price / rate) if rate else price
    if from_currency == "RUB" and to_currency == "CNY":
        rate = get_cny_to_rub()
        return round(price / rate) if rate else price
    if from_currency == "KRW" and to_currency == "JPY":
        krw_rate = get_krw_to_rub()
        jpy_rate = get_jpy_to_rub()
        if krw_rate and jpy_rate:
            return round(price * krw_rate / jpy_rate)
        return price
    if from_currency == "KRW" and to_currency == "SGD":
        krw_rate = get_krw_to_rub()
        sgd_rate = get_sgd_to_rub()
        if krw_rate and sgd_rate:
            return round(price * krw_rate / sgd_rate)
        return price
    return price


async def search_all_platforms(
    brand: str,
    item_type_ru: str,
    user_id: int,
    model: str = "",
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    price_currency: str = "KRW",
    limit_per_platform: int = 50,
) -> dict[str, list[GoofishItem]]:
    enabled = get_enabled_platforms(user_id)

    async def _search_one(platform: str) -> list[GoofishItem]:
        try:
            return await asyncio.wait_for(
                _do_search_one(platform),
                timeout=90.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Search timeout on %s (90s)", platform)
            return []
        except Exception as e:
            logger.error(f"Search error on {platform}: {e}")
            return []

    async def _do_search_one(platform: str) -> list[GoofishItem]:
        searcher_mod = PLATFORM_SEARCHERS.get(platform)
        if not searcher_mod:
            return []
        lang = PLATFORM_LANG.get(platform, "en")
        translated_type = _translate_type(item_type_ru, lang)
        mod = __import__(searcher_mod, fromlist=["search_by_brand_type"])
        plat_currency = PLATFORM_CURRENCY.get(platform, "KRW")
        plat_price_min = _convert_price(price_min, price_currency, plat_currency)
        plat_price_max = _convert_price(price_max, price_currency, plat_currency)

        queries = [translated_type]
        if model:
            queries.append(f"{translated_type} {model}".strip())

        async def _search(q: str) -> list[GoofishItem]:
            try:
                result = await mod.search_by_brand_type(
                    brand=brand,
                    item_type=q,
                    price_min=plat_price_min,
                    price_max=plat_price_max,
                    limit=limit_per_platform,
                )
                if result and result.items:
                    return result.items
            except Exception:
                pass
            return []

        raw_lists = await asyncio.gather(*[_search(q) for q in queries], return_exceptions=True)

        seen_ids: set[str] = set()
        items: list[GoofishItem] = []
        for r in raw_lists:
            if not isinstance(r, list):
                continue
            for item in r:
                key = f"{item.source}:{item.item_id}"
                if key not in seen_ids:
                    seen_ids.add(key)
                    items.append(item)

        if items and brand:
            brand_lower = brand.lower()
            before = len(items)
            filtered: list[GoofishItem] = []
            for i in items:
                if not i.location:
                    filtered.append(i)
                elif brand_lower in i.location.lower():
                    filtered.append(i)
                else:
                    logger.debug(f"Brand filter removed [{platform}] {i.title} (location={i.location!r})")
            items = filtered
            logger.info(f"Brand filter [{platform}]: {len(items)}/{before} kept")
        return items

    results: dict[str, list[GoofishItem]] = {}
    tasks = []
    for p in enabled:
        if p in PLATFORM_SEARCHERS:
            tasks.append(_search_one(p))

    platform_lists = await asyncio.gather(*tasks, return_exceptions=True)

    for p, lst in zip([p for p in enabled if p in PLATFORM_SEARCHERS], platform_lists):
        if isinstance(lst, list):
            results[p] = lst
        elif isinstance(lst, Exception):
            logger.error(f"Exception searching {p}: {lst}")
            results[p] = []
        else:
            results[p] = []

    return results


async def search_all_platforms_free_text(
    query: str,
    user_id: int,
    limit_per_platform: int = 100,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    price_currency: str = "KRW",
) -> dict[str, list[GoofishItem]]:
    enabled = get_enabled_platforms(user_id)

    async def _search_one(platform: str) -> list[GoofishItem]:
        try:
            return await asyncio.wait_for(
                _do_search_one(platform),
                timeout=90.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Search timeout on %s (90s)", platform)
            return []
        except Exception as e:
            logger.error(f"Search error on {platform}: {e}")
            return []

    async def _do_search_one(platform: str) -> list[GoofishItem]:
        searcher_mod = PLATFORM_SEARCHERS.get(platform)
        if not searcher_mod:
            return []
        mod = __import__(searcher_mod, fromlist=["search_by_brand_type"])
        plat_currency = PLATFORM_CURRENCY.get(platform, "KRW")
        plat_price_min = _convert_price(price_min, price_currency, plat_currency)
        plat_price_max = _convert_price(price_max, price_currency, plat_currency)
        result = await mod.search_by_brand_type(
            brand=query,
            item_type="",
            price_min=plat_price_min,
            price_max=plat_price_max,
            limit=limit_per_platform,
        )
        if result and result.items:
            return result.items
        return []

    results: dict[str, list[GoofishItem]] = {}
    tasks = []
    for p in enabled:
        if p in PLATFORM_SEARCHERS:
            tasks.append(_search_one(p))

    platform_lists = await asyncio.gather(*tasks, return_exceptions=True)

    for p, lst in zip([p for p in enabled if p in PLATFORM_SEARCHERS], platform_lists):
        if isinstance(lst, list):
            results[p] = lst
        elif isinstance(lst, Exception):
            logger.error(f"Exception searching {p}: {lst}")
            results[p] = []
        else:
            results[p] = []

    return results


def _merge_cross_platform(items: list[GoofishItem]) -> list[GoofishItem]:
    groups: dict[str, list[GoofishItem]] = {}
    for item in items:
        key = f"{item.title.lower().strip()}|{item.price_cny}"
        groups.setdefault(key, []).append(item)

    merged: list[GoofishItem] = []
    for group in groups.values():
        primary = group[0]
        for dup in group[1:]:
            pn = PLATFORM_INFO.get(dup.source, {}).get("name", dup.source)
            if pn not in primary.alt_sources:
                primary.alt_sources.append(pn)
            if dup.url not in primary.alt_urls:
                primary.alt_urls.append(dup.url)
        merged.append(primary)
    return merged


def merge_platform_results(
    results: dict[str, list[GoofishItem]],
    sort_by: str = "price",
) -> list[GoofishItem]:
    all_items: list[GoofishItem] = []
    for platform, items in results.items():
        for item in items:
            item.source = platform
            info = PLATFORM_INFO.get(platform, {})
            item.country = info.get("country", "")
            item.currency = info.get("currency", "")
        all_items.extend(items)

    all_items = _deduplicate(all_items)
    all_items = _merge_cross_platform(all_items)

    if sort_by == "price":
        all_items.sort(key=lambda x: x.price_cny)
    elif sort_by == "date":
        all_items.sort(key=lambda x: x.created_at or "", reverse=True)

    return all_items


async def search_all_platforms_smart(
    query: str,
    user_id: int,
    limit_per_platform: int = 100,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    price_currency: str = "KRW",
    use_cache: bool = True,
    cache_ttl: int = 300,
) -> dict[str, list[GoofishItem]]:
    """Умный поиск с пайплайном A→B→C и кэшированием.
    
    1. Exact match
    2. Fuzzy matching (RapidFuzz)
    3. Synonym expansion
    """
    enabled = get_enabled_platforms(user_id)
    cache = get_cache()
    cache_key = make_search_cache_key(query, enabled, price_min, price_max, price_currency)

    if use_cache:
        cached = await cache.get(cache_key)
        if cached is not None:
            logger.info(f"[SmartSearch] Cache hit for query='{query}'")
            return cached

    pipeline = get_smart_search()
    step_results = await pipeline.execute(
        query=query,
        platforms=enabled,
        user_id=user_id,
        limit_per_platform=limit_per_platform,
        price_min=price_min,
        price_max=price_max,
        price_currency=price_currency,
    )

    # Берём результаты первой успешной стратегии
    final_items: list[GoofishItem] = []
    used_strategy = "none"
    for res in step_results:
        if res.items:
            final_items = res.items
            used_strategy = res.strategy
            break

    if not final_items:
        logger.info(f"[SmartSearch] No items found for query='{query}' after all strategies")
        return {p: [] for p in enabled}

    # Группируем по платформам для возврата
    results_by_platform: dict[str, list[GoofishItem]] = {p: [] for p in enabled}
    for item in final_items:
        if item.source in results_by_platform:
            results_by_platform[item.source].append(item)

    logger.info(f"[SmartSearch] Found {len(final_items)} items via {used_strategy} for query='{query}'")

    if use_cache and final_items:
        await cache.set(cache_key, results_by_platform, ttl=cache_ttl)

    return results_by_platform
