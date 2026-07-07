import re
from datetime import datetime
from typing import Optional

from goofish_parser.scraper.models import GoofishItem, SearchCriteria, SearchResult
from goofish_parser.ff_scraper.client import search_products, get_categories


CLOTHING_RU_TO_KO = {
    "кроссовки": "운동화",
    "кеды": "단화",
    "ботинки": "부츠",
    "сапоги": "부츠",
    "футболка": "반팔 티셔츠",
    "рубашка": "셔츠",
    "свитер": "니트",
    "свитшот": "맨투맨",
    "толстовка": "맨투맨",
    "худи": "후드티",
    "куртка": "자켓",
    "бомбер": "봄버/블루종",
    "косуха": "가죽자켓",
    "джинсовка": "데님자켓",
    "пуховик": "패딩",
    "пальто": "코트",
    "ветровка": "바람막이",
    "джинсы": "데님팬츠",
    "штаны": "코튼팬츠",
    "брюки": "슬랙스",
    "шорты": "반바지",
    "платье": "원피스",
    "костюм": "셋업",
    "пиджак": "블레이저",
    "жилетка": "베스트",
    "лонгслив": "긴팔 티셔츠",
    "майка": "슬리브리스",
    "спортивный костюм": "트랙팬츠",
    "карго": "카고팬츠",
    "джоггеры": "조거팬츠",
    "треники": "스웨트팬츠",
    "легинсы": "레깅스",
    "шапка": "모자",
    "кепка": "야구모자",
    "панама": "버킷햇",
    "бейсболка": "야구모자",
    "рюкзак": "백팩",
    "сумка": "가방",
    "ремень": "벨트",
    "носки": "양말",
    "шарф": "목도리",
    "перчатки": "장갑",
    "часы": "시계",
    "очки": "안경",
    "браслет": "팔찌",
    "цепочка": "목걸이",
    "кольцо": "반지",
    "серьги": "귀걸이",
    "купальник": "수영복",
    "плавки": "수영복",
    "трусы": "팬티",
    "колготки": "스타킹",
    "сланцы": "슬리퍼",
    "тапки": "슬리퍼",
    "флиска": "플리스",
}

# Similar words groups for fuzzy fallback
SIMILAR_WORDS = {
    "штаны": ["джинсы", "брюки", "карго", "джоггеры", "треники"],
    "джинсы": ["штаны", "брюки", "карго"],
    "брюки": ["штаны", "джинсы", "слаксы"],
    "кроссовки": ["кеды", "ботинки", "сникерсы"],
    "кеды": ["кроссовки", "сланцы"],
    "ботинки": ["кроссовки", "сапоги"],
    "куртка": ["пуховик", "ветровка", "бомбер", "косуха", "джинсовка"],
    "свитер": ["свитшот", "толстовка", "худи", "лонгслив"],
    "свитшот": ["свитер", "толстовка", "худи"],
    "толстовка": ["свитер", "свитшот", "худи"],
    "худи": ["свитер", "свитшот", "толстовка"],
    "футболка": ["майка", "лонгслив", "поло"],
    "пуховик": ["куртка", "пальто", "ветровка"],
}


def _find_clothing_keywords(text: str) -> list[str]:
    text_lower = text.lower()
    found = []
    for ru_word in CLOTHING_RU_TO_KO:
        if ru_word in text_lower:
            found.append(ru_word)
    return found


def _find_similar(query_type: str) -> list[str]:
    query_lower = query_type.lower().strip()
    if query_lower in SIMILAR_WORDS:
        return SIMILAR_WORDS[query_lower]
    return []


SORT_OPTIONS = {
    "популярные": "POPULAR",
    "новые": "NEW",
    "просмотры": "HIGH_VIEW",
}


def _extract_item_id(url: str) -> str:
    m = re.search(r"[?&]id=(\d+)", url or "")
    return m.group(1) if m else ""


def _parse_price(price_str: str | int | float) -> float:
    try:
        return float(str(price_str).replace(",", "").replace("₩", "").strip())
    except (ValueError, AttributeError):
        return 0.0


def _build_search_query(criteria: SearchCriteria) -> str:
    parts = [criteria.brand]
    if criteria.item_type:
        ko_type = CLOTHING_RU_TO_KO.get(criteria.item_type, criteria.item_type)
        parts.append(ko_type)
    return " ".join(parts)


def _ff_item_to_model(raw: dict) -> GoofishItem | None:
    try:
        price = _parse_price(raw.get("price", 0))
        original_price = _parse_price(raw.get("original_price") or 0)
        item_id = str(raw.get("id", ""))
        title = str(raw.get("title") or "")
        brand = raw.get("brand") or ""
        condition = raw.get("condition") or ""
        size = raw.get("size") or ""
        images = raw.get("resizedSmallImages") or []
        like_count = int(raw.get("like_count") or 0)
        discount_rate = raw.get("discount_rate")
        created_at = raw.get("createdAt") or ""
        seller_info = raw.get("seller") or {}
        seller_id = str(seller_info.get("id", "")) if isinstance(seller_info, dict) else ""
        status = raw.get("status") or ""
        is_visible = bool(raw.get("is_visible", True))

        ext_url = raw.get("external_url") or ""
        if ext_url.startswith("http"):
            url = ext_url
        elif seller_id:
            url = f"https://fruitsfamily.com/seller/{seller_id}"
        else:
            url = f"https://fruitsfamily.com"

        return GoofishItem(
            item_id=item_id,
            title=title,
            price_cny=price,
            url=url,
            seller_id=seller_id,
            status=status,
            is_visible=is_visible,
            condition=condition,
            location=brand,
            badge=f"{like_count} ♥" if like_count else "",
            images=images,
            category_id="",
            price_original_cny=original_price,
            discount_rate=discount_rate,
            created_at=created_at,
        )
    except Exception:
        logger.exception("Failed to parse item")
        return None


async def search_items(criteria: SearchCriteria) -> SearchResult:
    query = _build_search_query(criteria)

    price_min = None
    price_max = None
    if criteria.price_min_cny is not None:
        price_min = int(criteria.price_min_cny)
    if criteria.price_max_cny is not None:
        price_max = int(criteria.price_max_cny)

    items = await search_products(
        query=query,
        sort="POPULAR",
        limit=criteria.limit,
        price_min=price_min,
        price_max=price_max,
    )

    if not items:
        return SearchResult(empty=True)

    parsed = [_ff_item_to_model(i) for i in items]
    parsed = [i for i in parsed if i is not None]
    filtered = [i for i in parsed if i.price_cny > 0]
    return SearchResult(items=filtered, empty=len(filtered) == 0)


async def search_by_brand_type(
    brand: str,
    item_type: str,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    limit: int = 30,
) -> SearchResult:
    criteria = SearchCriteria(
        brand=brand,
        item_type=item_type,
        price_min_cny=price_min,
        price_max_cny=price_max,
        limit=limit,
    )
    return await search_items(criteria)


async def search_products_free_text(
    query: str,
    sort: str = "NEW",
    limit: int = 30,
    auto_detect_clothing: bool = True,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
) -> list[GoofishItem]:
    search_query = query.strip()
    raw_items = []

    if auto_detect_clothing:
        clothing_words = _find_clothing_keywords(query)
        if clothing_words:
            for cw in clothing_words:
                ko = CLOTHING_RU_TO_KO[cw]
                search_query = search_query.replace(cw, ko, 1)

    raw_items = await search_products(query=search_query, sort=sort, limit=limit, show_only="selling",
                                      price_min=price_min, price_max=price_max)

    # Fallback: if converted query returns too few, try the original query
    if not raw_items:
        raw_items = await search_products(query=query.strip(), sort=sort, limit=limit, show_only="selling",
                                          price_min=price_min, price_max=price_max)

    # Fallback: try similar clothing types
    if not raw_items and auto_detect_clothing:
        clothing_words = _find_clothing_keywords(query)
        if clothing_words:
            for cw in clothing_words:
                similar = _find_similar(cw)
                for sim in similar:
                    ko = CLOTHING_RU_TO_KO.get(sim, sim)
                    fq = query.replace(cw, ko, 1)
                    raw_items = await search_products(query=fq, sort=sort, limit=limit, show_only="selling",
                                                      price_min=price_min, price_max=price_max)
                    if raw_items:
                        break
                if raw_items:
                    break

    if not raw_items:
        return []

    parsed = [_ff_item_to_model(i) for i in raw_items]
    parsed = [i for i in parsed if i is not None]
    sold_keywords = ["sold", "reserved", "판매완료", "예약중"]
    filtered = [i for i in parsed if i.price_cny > 0 and i.status not in sold_keywords]
    return filtered



