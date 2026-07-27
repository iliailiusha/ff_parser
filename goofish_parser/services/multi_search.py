import asyncio
import logging
import re
from typing import Optional

from rapidfuzz import fuzz

from goofish_parser.scraper.models import GoofishItem, PLATFORM_INFO, ALL_PLATFORMS, COUNTRY_PLATFORMS
from goofish_parser.storage.db import get_enabled_platforms
from goofish_parser.services.exchange_rate import get_krw_to_rub, get_jpy_to_rub, get_sgd_to_rub, get_cny_to_rub
from goofish_parser.services.cache import get_cache, make_search_cache_key
from goofish_parser.services.smart_search import get_smart_search

logger = logging.getLogger(__name__)

FUZZY_BRAND_THRESHOLD = 85

_NORMALIZE_RE = re.compile(r"[-–—\s]+")

def _normalize_text(text: str) -> str:
    """Strip hyphens/dashes, collapse whitespace, lowercase."""
    return _NORMALIZE_RE.sub(" ", text).strip().lower()

def _compact_text(text: str) -> str:
    """Remove all separators entirely for matching (gt-2160 -> gt2160)."""
    return re.sub(r"[-–—\s]", "", text).lower()

def _get_item_text(item: GoofishItem) -> str:
    """Combine title and description for full-text search."""
    parts = [item.title or ""]
    if item.description:
        parts.append(item.description)
    return " ".join(parts).lower()


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

CLOTHING_JA: dict[str, str] = {
    "кроссовки": "スニーカー",
    "кеды": "スニーカー",
    "ботинки": "ブーツ",
    "сапоги": "ブーツ",
    "футболка": "Tシャツ",
    "рубашка": "シャツ",
    "свитер": "セーター",
    "свитшот": "スウェット",
    "толстовка": "スウェット",
    "худи": "パーカー",
    "куртка": "ジャケット",
    "пуховик": "ダウン",
    "пальто": "コート",
    "ветровка": "ウィンドブレーカー",
    "джинсы": "ジーンズ",
    "штаны": "パンツ",
    "брюки": "ズボン",
    "шорты": "ショーツ",
    "платье": "ワンピース",
    "костюм": "スーツ",
    "пиджак": "ブレザー",
    "жилетка": "ベスト",
    "лонгслив": "長袖Tシャツ",
    "майка": "タンクトップ",
    "спортивный костюм": "トラックスーツ",
    "бомбер": "ボンバージャケット",
    "косуха": "ライダースジャケット",
    "джинсовка": "デニムジャケット",
    "флиска": "フリース",
    "карго": "カーゴパンツ",
    "джоггеры": "ジョガーパンツ",
    "треники": "スウェットパンツ",
    "легинсы": "レギンス",
    "шапка": "帽子",
    "кепка": "キャップ",
    "рюкзак": "バックパック",
    "сумка": "バッグ",
    "ремень": "ベルト",
    "носки": "靴下",
    "шарф": "マフラー",
    "перчатки": "手袋",
    "часы": "時計",
    "очки": "眼鏡",
    "браслет": "ブレスレット",
    "цепочка": "ネックレス",
    "кольцо": "指輪",
    "серьги": "イヤリング",
    "купальник": "水着",
    "плавки": "水着",
    "трусы": "下着",
    "колготки": "タイツ",
    "сланцы": "サンダル",
    "тапки": "スリッパ",
    "панама": "バケットハット",
    "бейсболка": "キャップ",
    "бандана": "バンダナ",
}

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

# All type keywords per language for type filtering
_ALL_TYPE_KEYWORDS: dict[str, set[str]] = {}
for _ru, _ko in CLOTHING_RU_TO_KO.items():
    for w in _ko.replace("/", " ").split():
        _ALL_TYPE_KEYWORDS.setdefault("ko", set()).add(w.lower())
for _ru, _ja in CLOTHING_JA.items():
    for w in _ja.replace("/", " ").split():
        _ALL_TYPE_KEYWORDS.setdefault("ja", set()).add(w.lower())
for _ru, _en in CLOTHING_EN.items():
    for w in _en.replace("/", " ").split():
        _ALL_TYPE_KEYWORDS.setdefault("en", set()).add(w.lower())
# Add English keywords to all languages as fallback
for lang in ("ko", "ja"):
    _ALL_TYPE_KEYWORDS[lang].update(_ALL_TYPE_KEYWORDS.get("en", set()))
# Add Russian keywords to all languages
_ALL_TYPE_KEYWORDS["en"].update(w.lower() for w in CLOTHING_RU_TO_KO)
_ALL_TYPE_KEYWORDS["ko"].update(w.lower() for w in CLOTHING_RU_TO_KO)
_ALL_TYPE_KEYWORDS["ja"].update(w.lower() for w in CLOTHING_RU_TO_KO)


_FF_CATEGORY_MAP: dict[str, set[str]] = {
    "кроссовки": {"신발"},
    "кеды": {"신발"},
    "ботинки": {"신발"},
    "сапоги": {"신발"},
    "сланцы": {"신발"},
    "тапки": {"신발"},
    "футболка": {"상의"},
    "рубашка": {"상의"},
    "свитер": {"상의"},
    "свитшот": {"상의"},
    "толстовка": {"상의"},
    "лонгслив": {"상의"},
    "майка": {"상의"},
    "пиджак": {"상의"},
    "жилетка": {"상의"},
    "худи": {"상의", "아우터"},
    "куртка": {"아우터"},
    "пуховик": {"아우터"},
    "пальто": {"아우터"},
    "ветровка": {"아우터"},
    "бомбер": {"아우터"},
    "косуха": {"아우터"},
    "джинсовка": {"아우터"},
    "флиска": {"아우터"},
    "джинсы": {"하의"},
    "штаны": {"하의"},
    "брюки": {"하의"},
    "шорты": {"하의"},
    "карго": {"하의"},
    "джоггеры": {"하의"},
    "треники": {"하의"},
    "легинсы": {"하의"},
    "платье": {"원피스"},
    "костюм": {"셋업"},
    "спортивный костюм": {"셋업"},
    "шапка": {"모자"},
    "кепка": {"모자"},
    "панама": {"모자"},
    "бейсболка": {"모자"},
    "рюкзак": {"가방"},
    "сумка": {"가방"},
    "ремень": {"액세서리"},
    "носки": {"양말"},
    "шарф": {"액세서리"},
    "перчатки": {"액세서리"},
    "часы": {"시계"},
    "очки": {"액세서리"},
    "браслет": {"액세서리"},
    "цепочка": {"액세서리"},
    "кольцо": {"반지"},
    "серьги": {"액세서리"},
    "купальник": {"수영복"},
    "плавки": {"수영복"},
    "трусы": {"하의"},
    "колготки": {"하의"},
}

_TYPE_SYNONYMS: dict[str, dict[str, set[str]]] = {
    "кроссовки": {
        "ko": {"스니커즈", "런닝화"},
        "ja": {"シューズ"},
        "en": {"running shoes", "trainers"},
    },
    "кеды": {
        "ko": {"스니커즈"},
    },
    "футболка": {
        "en": {"tee"},
    },
    "куртка": {
        "ko": {"져지", "자켓", "집업", "점퍼"},
    },
    "свитшот": {
        "ko": {"져지", "맨투맨"},
    },
    "толстовка": {
        "ko": {"져지", "맨투맨"},
    },
    "худи": {
        "ko": {"후드", "후드티"},
    },
    "штаны": {
        "en": {"trousers"},
        "ko": {"바지"},
    },
    "брюки": {
        "ko": {"바지"},
    },
    "купальник": {
        "ko": {"비키니"},
    },
}


def _get_type_keywords(item_type_ru: str, lang: str) -> set[str]:
    if not item_type_ru:
        return set()
    keywords = set()
    ru_lower = item_type_ru.lower()
    if lang == "ko":
        kw = CLOTHING_RU_TO_KO.get(ru_lower, "")
        keywords.update(w.lower() for w in kw.replace("/", " ").split())
    elif lang == "ja":
        kw = CLOTHING_JA.get(ru_lower, "")
        keywords.update(w.lower() for w in kw.replace("/", " ").split())
    else:
        kw = CLOTHING_EN.get(ru_lower, "")
        keywords.update(w.lower() for w in kw.replace("/", " ").split())
    # Always add English and Russian variants
    en_kw = CLOTHING_EN.get(ru_lower, "")
    keywords.update(w.lower() for w in en_kw.replace("/", " ").split())
    keywords.add(ru_lower)
    # Add per-language synonyms
    syns = _TYPE_SYNONYMS.get(ru_lower, {})
    if syns:
        for lang_syn in (lang, "en"):
            keywords.update(syns.get(lang_syn, set()))
    return keywords


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


MODEL_TRANSLATIONS: dict[str, dict[str, str]] = {
    "raf simons": {"ko": "라프 시몬스", "en": "Raf Simons", "ja": "ラフ・シモンズ", "zh": "拉夫·西蒙斯"},
    "air force 1": {"ko": "에어포스1", "en": "Air Force 1", "ja": "エアフォース1", "zh": "空军一号"},
    "air jordan 1": {"ko": "에어조던1", "en": "Air Jordan 1", "ja": "エアジョーダン1", "zh": "乔丹1代"},
    "air jordan 4": {"ko": "에어조던4", "en": "Air Jordan 4", "ja": "エアジョーダン4", "zh": "乔丹4代"},
    "air jordan 11": {"ko": "에어조던11", "en": "Air Jordan 11", "ja": "エアジョーダン11", "zh": "乔丹11代"},
    "dunk low": {"ko": "덩크 로우", "en": "Dunk Low", "ja": "ダンク ロー", "zh": " Dunk Low"},
    "dunk high": {"ko": "덩크 하이", "en": "Dunk High", "ja": "ダンク ハイ", "zh": " Dunk High"},
    "yeezy 350": {"ko": "이지 350", "en": "Yeezy 350", "ja": "イージー 350", "zh": "Yeezy 350"},
    "yeezy 700": {"ko": "이지 700", "en": "Yeezy 700", "ja": "イージー 700", "zh": "Yeezy 700"},
    "new balance 990": {"ko": "뉴발란스 990", "en": "New Balance 990", "ja": "ニューバランス 990", "zh": "新百伦 990"},
    "new balance 550": {"ko": "뉴발란스 550", "en": "New Balance 550", "ja": "ニューバランス 550", "zh": "新百伦 550"},
    "samba": {"ko": "삼바", "en": "Samba", "ja": "サンバ", "zh": "桑巴"},
    "gazelle": {"ko": "가젤", "en": "Gazelle", "ja": "ガゼル", "zh": "羚羊"},
    "stan smith": {"ko": "스탠 스미스", "en": "Stan Smith", "ja": "スタンスミス", "zh": "斯坦史密斯"},
    "ultraboost": {"ko": "울트라부스트", "en": "Ultraboost", "ja": "ウルトラブースト", "zh": "Ultraboost"},
    "nmd": {"ko": "NMD", "en": "NMD", "ja": "NMD", "zh": "NMD"},
    "speed trainer": {"ko": "스피드 트레이너", "en": "Speed Trainer", "ja": "スピードトレーナー", "zh": "Speed Trainer"},
    "triple s": {"ko": "트리플 S", "en": "Triple S", "ja": "トリプル S", "zh": "Triple S"},
    "old skool": {"ko": "올드 스쿨", "en": "Old Skool", "ja": "オールドスクール", "zh": "Old Skool"},
    "authentic": {"ko": "어센틱", "en": "Authentic", "ja": "オーセンティック", "zh": "Authentic"},
    "era": {"ko": "에라", "en": "Era", "ja": "エラ", "zh": "Era"},
    "slip on": {"ko": "슬립온", "en": "Slip On", "ja": "スリッポン", "zh": "Slip On"},
    "classic leather": {"ko": "클래식 레더", "en": "Classic Leather", "ja": "クラシック レザー", "zh": "Classic Leather"},
    "club c": {"ko": "클럽 C", "en": "Club C", "ja": "クラブ C", "zh": "Club C"},
    "chuck 70": {"ko": "척 70", "en": "Chuck 70", "ja": "チャック 70", "zh": "Chuck 70"},
    "chuck taylor": {"ko": "척 테일러", "en": "Chuck Taylor", "ja": "チャックテイラー", "zh": "Chuck Taylor"},
    "gel lyte": {"ko": "젤 라이트", "en": "Gel Lyte", "ja": "ゲルライト", "zh": "Gel Lyte"},
    "gel kayano": {"ko": "젤 카야노", "en": "Gel Kayano", "ja": "ゲルカヤノ", "zh": "Gel Kayano"},
    "gt-2160": {"ko": "GT-2160", "en": "GT-2160", "ja": "GT-2160", "zh": "GT-2160"},
    "mexico 66": {"ko": "멕시코 66", "en": "Mexico 66", "ja": "メキシコ 66", "zh": "Mexico 66"},
}


def translate_model_for_platform(model: str, lang: str) -> str:
    ml = model.lower().strip()
    if ml in MODEL_TRANSLATIONS:
        return MODEL_TRANSLATIONS[ml].get(lang, model)
    return model


def _translate_type(item_type: str, lang: str) -> str:
    if not item_type:
        return ""
    if lang == "ko":
        return CLOTHING_RU_TO_KO.get(item_type, item_type)
    if lang == "ja":
        return CLOTHING_JA.get(item_type, item_type)
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


async def _convert_price(price: Optional[float], from_currency: str, to_currency: str) -> Optional[float]:
    if price is None or from_currency == to_currency:
        return price
    if from_currency == "RUB" and to_currency == "KRW":
        rate = await get_krw_to_rub()
        return round(price / rate) if rate else price
    if from_currency == "RUB" and to_currency == "JPY":
        rate = await get_jpy_to_rub()
        return round(price / rate) if rate else price
    if from_currency == "RUB" and to_currency == "SGD":
        rate = await get_sgd_to_rub()
        return round(price / rate) if rate else price
    if from_currency == "RUB" and to_currency == "CNY":
        rate = await get_cny_to_rub()
        return round(price / rate) if rate else price
    if from_currency == "KRW" and to_currency == "JPY":
        krw_rate = await get_krw_to_rub()
        jpy_rate = await get_jpy_to_rub()
        if krw_rate and jpy_rate:
            return round(price * krw_rate / jpy_rate)
        return price
    if from_currency == "KRW" and to_currency == "SGD":
        krw_rate = await get_krw_to_rub()
        sgd_rate = await get_sgd_to_rub()
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
    limit_per_platform: int = 500,
) -> dict[str, list[GoofishItem]]:
    enabled = get_enabled_platforms(user_id)

    async def _search_one(platform: str) -> list[GoofishItem]:
        timeout = 10.0 if platform == "carousell" else 180.0
        try:
            return await asyncio.wait_for(
                _do_search_one(platform),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("Search timeout on %s (%ss)", platform, timeout)
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
        plat_price_min = await _convert_price(price_min, price_currency, plat_currency)
        plat_price_max = await _convert_price(price_max, price_currency, plat_currency)

        async def _search(q: str, pass_as_item_type: bool = True) -> list[GoofishItem]:
            try:
                if pass_as_item_type:
                    result = await mod.search_by_brand_type(
                        brand=brand,
                        item_type=q,
                        price_min=plat_price_min,
                        price_max=plat_price_max,
                        limit=limit_per_platform,
                    )
                else:
                    result = await mod.search_by_brand_type(
                        brand=q,
                        item_type="",
                        price_min=plat_price_min,
                        price_max=plat_price_max,
                        limit=limit_per_platform,
                    )
                if result and result.items:
                    return result.items
            except Exception:
                pass
            return []

        # For FruitsFamily: skip translated_type in search when brand+model specified,
        # because Korean "운동화" can kill AND-matching on items with English titles.
        if platform == "fruitsfamily" and brand and model:
            base_query = f"{brand} {model}"
            items_original = await _search(base_query, pass_as_item_type=False)
        else:
            base_query = translated_type
            if model:
                base_query = f"{translated_type} {model}".strip()
            items_original = await _search(base_query, pass_as_item_type=True)

        if not items_original:
            return []

        items_combined = list(items_original)

        if brand:
            brand_lower = brand.lower()
            brand_norm = _normalize_text(brand)
            brand_compact = _compact_text(brand)
            before = len(items_combined)
            brand_filtered: list[GoofishItem] = []
            for i in items_combined:
                title_lower = (i.title or "").lower()
                location_lower = (i.location or "").lower()
                text_lower = _get_item_text(i)
                text_norm = _normalize_text(text_lower)
                text_compact = _compact_text(text_lower)
                if brand_lower in location_lower or brand_lower in title_lower:
                    brand_filtered.append(i)
                elif brand_lower in text_lower:
                    brand_filtered.append(i)
                elif brand_compact and brand_compact in text_compact:
                    brand_filtered.append(i)
                elif fuzz.partial_ratio(brand_norm, text_norm) >= FUZZY_BRAND_THRESHOLD:
                    brand_filtered.append(i)
                else:
                    logger.debug(f"Brand filter removed [{platform}] {i.title} (location={i.location!r})")
            items_combined = brand_filtered
            logger.info(f"Brand filter [{platform}]: {len(items_combined)}/{before} kept")

        if item_type_ru:
            type_before = len(items_combined)
            allowed_cats = _FF_CATEGORY_MAP.get(item_type_ru) if platform == "fruitsfamily" else None
            searched_keywords = _get_type_keywords(item_type_ru, lang)
            all_keywords = _ALL_TYPE_KEYWORDS.get(lang, set())
            other_keywords = all_keywords - searched_keywords
            type_filtered: list[GoofishItem] = []
            for i in items_combined:
                # Category-based filter (FruitsFamily only, items with category field)
                if platform == "fruitsfamily" and allowed_cats and i.category:
                    if i.category in allowed_cats:
                        type_filtered.append(i)
                    else:
                        logger.debug(f"Type filter removed [{platform}] {i.title} (category={i.category!r})")
                    continue
                # Title-based filter (fallback for items without category)
                text_lower = _get_item_text(i)
                if any(kw in text_lower for kw in searched_keywords):
                    type_filtered.append(i)
                elif other_keywords and any(kw in text_lower for kw in other_keywords):
                    logger.debug(f"Type filter removed [{platform}] {i.title} (type mismatch)")
                else:
                    type_filtered.append(i)
            items_combined = type_filtered
            logger.info(f"Type filter [{platform}]: {len(items_combined)}/{type_before} kept")

        if model:
            model_before = len(items_combined)
            model_lower = model.lower().strip()
            orig_words = [w for w in model_lower.split() if len(w) > 1]
            orig_norm = _normalize_text(model_lower)
            orig_compact = _compact_text(model_lower)
            translated_model = translate_model_for_platform(model_lower, lang).lower()
            trans_words = [w for w in translated_model.split() if len(w) > 1 and w not in orig_words]
            trans_norm = _normalize_text(translated_model) if translated_model != model_lower else ""
            trans_compact = _compact_text(translated_model) if translated_model != model_lower else ""
            model_filtered: list[GoofishItem] = []
            for i in items_combined:
                text_lower = _get_item_text(i)
                text_norm = _normalize_text(text_lower)
                text_compact = _compact_text(text_lower)
                # 1) All original words in combined text
                if all(w in text_lower for w in orig_words):
                    model_filtered.append(i)
                # 2) All translated words in combined text
                elif trans_words and all(w in text_lower for w in trans_words):
                    model_filtered.append(i)
                # 3) Normalized match (e.g. "GT-2160" matches "gt 2160" in title)
                elif orig_norm and orig_norm in text_norm:
                    model_filtered.append(i)
                elif trans_norm and trans_norm in text_norm:
                    model_filtered.append(i)
                # 4) Compact match (e.g. "GT-2160" matches "gt2160" in title)
                elif orig_compact and orig_compact in text_compact:
                    model_filtered.append(i)
                elif trans_compact and trans_compact in text_compact:
                    model_filtered.append(i)
                else:
                    logger.debug(f"Model filter removed [{platform}] {i.title} (missing model)")
            items_combined = model_filtered
            logger.info(f"Model filter [{platform}]: {len(items_combined)}/{model_before} kept")

        return items_combined

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
    user_id: int = 0,
    limit_per_platform: int = 500,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    price_currency: str = "KRW",
    platforms: Optional[list[str]] = None,
) -> dict[str, list[GoofishItem]]:
    if platforms is not None:
        enabled = [p for p in platforms if p in PLATFORM_SEARCHERS]
    else:
        enabled = get_enabled_platforms(user_id)

    # Detect Russian clothing type words in the query for per-platform translation
    query_lower = query.lower()
    clothing_types_found: list[str] = []
    for ru_word in CLOTHING_RU_TO_KO:
        if ru_word in query_lower:
            clothing_types_found.append(ru_word)

    async def _search_one(platform: str) -> list[GoofishItem]:
        timeout = 10.0 if platform == "carousell" else 180.0
        try:
            return await asyncio.wait_for(
                _do_search_one(platform),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("Search timeout on %s (%ss)", platform, timeout)
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
        plat_price_min = await _convert_price(price_min, price_currency, plat_currency)
        plat_price_max = await _convert_price(price_max, price_currency, plat_currency)

        # Translate clothing types in query for this platform's language
        lang = PLATFORM_LANG.get(platform, "en")
        platform_query = query
        for ru_word in clothing_types_found:
            translated = _translate_type(ru_word, lang)
            if translated and translated != ru_word:
                platform_query = platform_query.replace(ru_word, translated, 1)

        if platform_query != query:
            logger.debug(f"[{platform}] Translated query: '{query}' -> '{platform_query}'")

        result = await mod.search_by_brand_type(
            brand=platform_query,
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

    for p, lst in zip(enabled, platform_lists):
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
    limit_per_platform: int = 500,
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
