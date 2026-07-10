import logging
import re
from typing import Any, Optional

from goofish_parser.scraper.models import GoofishItem, SearchCriteria, SearchResult, PLATFORM_INFO
from goofish_parser.mercari_scraper.client import search_mercari

logger = logging.getLogger(__name__)


def _parse_price_jpy(price_val: Any) -> float:
    try:
        return float(str(price_val).replace(",", "").replace("¥", "").strip())
    except (ValueError, AttributeError):
        return 0.0


def _mercari_item_to_model(raw: dict) -> Optional[GoofishItem]:
    try:
        item_id = str(raw.get("id", ""))
        title = str(raw.get("name") or "")
        price = _parse_price_jpy(raw.get("price", 0))
        description = str(raw.get("description") or "")
        condition = str(raw.get("condition") or "")
        status = str(raw.get("status") or "")
        location = str(raw.get("shippingFromArea") or "")
        seller_info = raw.get("seller") or {}
        seller_id = str(seller_info.get("id", "")) if isinstance(seller_info, dict) else ""
        photos = raw.get("photos") or []
        images = [p.get("url", "") for p in photos if isinstance(p, dict)]
        created_at = str(raw.get("createdAt") or "")
        brand_info = raw.get("brand") or {}
        brand_name = brand_info.get("name", "") if isinstance(brand_info, dict) else ""
        badge = brand_name if brand_name else ""

        url = f"https://www.mercari.com/item/{item_id}/"

        return GoofishItem(
            item_id=item_id,
            title=title,
            price_cny=price,
            url=url,
            condition=condition,
            location=location,
            badge=badge,
            images=images,
            seller_id=seller_id,
            status=status,
            created_at=created_at,
            source="mercari",
            country=PLATFORM_INFO["mercari"]["country"],
            currency=PLATFORM_INFO["mercari"]["currency"],
            seller_extra_1h=0,
        )
    except Exception:
        logger.exception("Failed to parse Mercari item")
        return None


async def search_items(criteria: SearchCriteria) -> SearchResult:
    query_parts = [criteria.brand]
    if criteria.item_type:
        query_parts.append(criteria.item_type)
    query = " ".join(query_parts)

    price_min = int(criteria.price_min_cny) if criteria.price_min_cny is not None else None
    price_max = int(criteria.price_max_cny) if criteria.price_max_cny is not None else None

    raw_items = await search_mercari(query, max_pages=10, page_size=100)

    if not raw_items:
        return SearchResult(empty=True)

    parsed = [_mercari_item_to_model(i) for i in raw_items]
    parsed = [i for i in parsed if i is not None and i.price_cny > 0]

    if price_min is not None:
        parsed = [i for i in parsed if i.price_cny >= price_min]
    if price_max is not None:
        parsed = [i for i in parsed if i.price_cny <= price_max]

    return SearchResult(items=parsed, empty=len(parsed) == 0)


async def search_by_brand_type(
    brand: str,
    item_type: str,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    limit: int = 100,
) -> SearchResult:
    criteria = SearchCriteria(
        brand=brand,
        item_type=item_type,
        price_min_cny=price_min,
        price_max_cny=price_max,
        limit=limit,
    )
    return await search_items(criteria)
