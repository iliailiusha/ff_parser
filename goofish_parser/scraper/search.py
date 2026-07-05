import re
from typing import Optional

from goofish_parser.scraper.models import GoofishItem, SearchCriteria
from goofish_parser.scraper.session import search_page


def _extract_item_id(url: str) -> str:
    m = re.search(r"[?&]id=(\d+)", url or "")
    return m.group(1) if m else ""


def _parse_price(price_str: str) -> float:
    try:
        return float(price_str.replace(",", "").replace("¥", "").strip())
    except (ValueError, AttributeError):
        return 0.0


def _build_search_query(criteria: SearchCriteria) -> str:
    parts = [criteria.brand, criteria.item_type]
    return " ".join(parts)


def _filter_by_price(items: list[GoofishItem], criteria: SearchCriteria) -> list[GoofishItem]:
    filtered = []
    for item in items:
        if criteria.price_min_cny is not None and item.price_cny < criteria.price_min_cny:
            continue
        if criteria.price_max_cny is not None and item.price_cny > criteria.price_max_cny:
            continue
        filtered.append(item)
    return filtered


async def search_items(criteria: SearchCriteria) -> list[GoofishItem]:
    query = _build_search_query(criteria)
    result = await search_page(query, limit=criteria.limit)

    if result.get("requiresAuth"):
        return []
    if result.get("blocked"):
        return []
    if result.get("empty"):
        return []

    items = []
    for raw in result.get("items", []):
        price = _parse_price(raw.get("price", "0"))
        attrs = raw.get("attrs", [])

        item = GoofishItem(
            item_id=_extract_item_id(raw.get("url", "")),
            title=raw.get("title", ""),
            price_cny=price,
            url=raw.get("url", ""),
            condition=attrs[0] if len(attrs) > 0 else "",
            location=raw.get("location", ""),
            badge=raw.get("badge", ""),
        )
        items.append(item)

    return _filter_by_price(items, criteria)


async def search_by_brand_type(
    brand: str,
    item_type: str,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    limit: int = 30,
) -> list[GoofishItem]:
    criteria = SearchCriteria(
        brand=brand,
        item_type=item_type,
        price_min_cny=price_min,
        price_max_cny=price_max,
        limit=limit,
    )
    return await search_items(criteria)
