import asyncio
import logging
from typing import Optional

from goofish_parser.scraper.models import GoofishItem, PLATFORM_INFO, ALL_PLATFORMS, COUNTRY_PLATFORMS
from goofish_parser.storage.db import get_enabled_platforms
from goofish_parser.services.exchange_rate import get_krw_to_rub, get_jpy_to_rub, get_sgd_to_rub

logger = logging.getLogger(__name__)


PLATFORM_LANG: dict[str, str] = {
    "fruitsfamily": "ko",
    "bunjang": "ko",
    "carousell": "en",
    "mercari_jp": "ja",
}

PLATFORM_CURRENCY: dict[str, str] = {
    "fruitsfamily": "KRW",
    "bunjang": "KRW",
    "carousell": "SGD",
    "mercari_jp": "JPY",
}

PLATFORM_SEARCHERS: dict[str, str] = {
    "fruitsfamily": "goofish_parser.ff_scraper.search",
    "bunjang": "goofish_parser.bunjang_scraper.search",
    "carousell": "goofish_parser.carousell_scraper.search",
    "mercari_jp": "goofish_parser.mercari_jp_scraper.search",
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
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    price_currency: str = "KRW",
    limit_per_platform: int = 50,
) -> dict[str, list[GoofishItem]]:
    enabled = get_enabled_platforms(user_id)

    async def _search_one(platform: str) -> list[GoofishItem]:
        try:
            searcher_mod = PLATFORM_SEARCHERS.get(platform)
            if not searcher_mod:
                return []
            lang = PLATFORM_LANG.get(platform, "en")
            translated_type = _translate_type(item_type_ru, lang)
            mod = __import__(searcher_mod, fromlist=["search_by_brand_type"])
            plat_currency = PLATFORM_CURRENCY.get(platform, "KRW")
            plat_price_min = _convert_price(price_min, price_currency, plat_currency)
            plat_price_max = _convert_price(price_max, price_currency, plat_currency)
            result = await mod.search_by_brand_type(
                brand=brand,
                item_type=translated_type,
                price_min=plat_price_min,
                price_max=plat_price_max,
                limit=limit_per_platform,
            )
            if result and result.items:
                items = result.items
                if brand:
                    brand_lower = brand.lower()
                    before = len(items)
                    filtered = []
                    for i in items:
                        if not i.location:
                            filtered.append(i)
                        elif brand_lower in i.location.lower():
                            filtered.append(i)
                        else:
                            logger.debug(f"Brand filter removed [{platform}] {i.title} (location={i.location!r})")
                    items = filtered
                    logger.info(f"Brand filter [{platform}]: {len(items)}/{before} kept (brand={brand!r})")
                return items
            return []
        except Exception as e:
            logger.error(f"Search error on {platform}: {e}")
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
        except Exception as e:
            logger.error(f"Search error on {platform}: {e}")
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
