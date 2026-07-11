import asyncio
import logging
from typing import Optional

from goofish_parser.scraper.models import GoofishItem, PLATFORM_INFO, ALL_PLATFORMS, COUNTRY_PLATFORMS
from goofish_parser.storage.db import get_enabled_platforms

logger = logging.getLogger(__name__)


PLATFORM_LANG: dict[str, str] = {
    "fruitsfamily": "ko",
    "bunjang": "ko",
    "carousell": "en",
    "mercari_jp": "ja",
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
    words = item_type.split()
    translated = []
    for w in words:
        if lang == "ko":
            translated.append(CLOTHING_RU_TO_KO.get(w, w))
        elif lang == "ja":
            translated.append(CLOTHING_EN.get(w, w))
        else:
            translated.append(CLOTHING_EN.get(w, w))
    return " ".join(translated)


def _deduplicate(items: list[GoofishItem]) -> list[GoofishItem]:
    seen: set[str] = set()
    result: list[GoofishItem] = []
    for item in items:
        key = f"{item.source}:{item.item_id}"
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


async def search_all_platforms(
    brand: str,
    item_type_ru: str,
    user_id: int,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
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
            result = await mod.search_by_brand_type(
                brand=brand,
                item_type=translated_type,
                price_min=price_min,
                price_max=price_max,
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


async def search_all_platforms_free_text(
    query: str,
    user_id: int,
    limit_per_platform: int = 100,
) -> dict[str, list[GoofishItem]]:
    enabled = get_enabled_platforms(user_id)

    async def _search_one(platform: str) -> list[GoofishItem]:
        try:
            searcher_mod = PLATFORM_SEARCHERS.get(platform)
            if not searcher_mod:
                return []
            mod = __import__(searcher_mod, fromlist=["search_by_brand_type"])
            result = await mod.search_by_brand_type(
                brand=query,
                item_type="",
                price_min=None,
                price_max=None,
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

    if sort_by == "price":
        all_items.sort(key=lambda x: x.price_cny)
    elif sort_by == "date":
        all_items.sort(key=lambda x: x.created_at or "", reverse=True)

    return all_items
