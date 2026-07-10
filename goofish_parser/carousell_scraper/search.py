import logging
from typing import Any, Optional

from goofish_parser.scraper.models import GoofishItem, SearchCriteria, SearchResult, PLATFORM_INFO
from goofish_parser.carousell_scraper.client import search_carousell

logger = logging.getLogger(__name__)


def _parse_price_sgd(price_val: Any) -> float:
    try:
        return float(str(price_val).replace(",", "").replace("SGD", "").replace("$", "").strip())
    except (ValueError, AttributeError):
        return 0.0


def _carousell_item_to_model(raw: dict) -> Optional[GoofishItem]:
    try:
        item_id = str(raw.get("id", ""))
        title = str(raw.get("title", "") or raw.get("name", ""))
        price = _parse_price_sgd(raw.get("price", 0))
        description = str(raw.get("description", "") or "")
        condition = str(raw.get("condition", "") or "")
        status = str(raw.get("status", "") or "")
        location_raw = raw.get("location", "") or raw.get("country", "")
        location = str(location_raw) if isinstance(location_raw, str) else str(location_raw.get("name", ""))
        seller_data = raw.get("seller", {}) or {}
        if not isinstance(seller_data, dict):
            seller_data = {}
        seller_id = str(seller_data.get("id", "") or "")
        images_raw = raw.get("images", []) or raw.get("photos", [])
        images = []
        for img in images_raw:
            if isinstance(img, str):
                images.append(img)
            elif isinstance(img, dict):
                url = img.get("url", "") or img.get("path", "")
                if url:
                    images.append(url)
        created_at = str(raw.get("createdAt", "") or raw.get("created_at", "") or "")
        badge = raw.get("brand", "") or raw.get("category", "") or ""

        url = f"https://www.carousell.com/p/{item_id}"

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
            source="carousell",
            country=PLATFORM_INFO["carousell"]["country"],
            currency=PLATFORM_INFO["carousell"]["currency"],
            seller_extra_1h=0,
        )
    except Exception:
        logger.exception("Failed to parse Carousell item")
        return None


async def search_items(criteria: SearchCriteria) -> SearchResult:
    query_parts = [criteria.brand]
    if criteria.item_type:
        query_parts.append(criteria.item_type)
    query = " ".join(query_parts)

    price_min = int(criteria.price_min_cny) if criteria.price_min_cny is not None else None
    price_max = int(criteria.price_max_cny) if criteria.price_max_cny is not None else None

    raw_items = await search_carousell(
        query, limit=50, count=5,
        price_min=price_min, price_max=price_max,
    )

    if not raw_items:
        return SearchResult(empty=True)

    parsed = [_carousell_item_to_model(i) for i in raw_items]
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
