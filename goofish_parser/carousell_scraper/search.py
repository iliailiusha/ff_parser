import logging
from typing import Any, Optional

from goofish_parser.scraper.models import GoofishItem, SearchCriteria, SearchResult, PLATFORM_INFO
from goofish_parser.carousell_scraper.client import search_carousell, CAROUSELL_COUNTRIES, DEFAULT_COUNTRY

logger = logging.getLogger(__name__)


def _parse_price(val: Any) -> float:
    try:
        return float(str(val).replace(",", "").replace("SGD", "").replace("$", "").strip())
    except (ValueError, AttributeError):
        return 0.0


def _carousell_item_to_model(raw: dict) -> Optional[GoofishItem]:
    try:
        item_id = str(raw.get("id", ""))
        title = str(raw.get("title") or raw.get("name", ""))
        price = _parse_price(raw.get("price", 0))

        images_raw = raw.get("images", [])
        images = []
        if images_raw and isinstance(images_raw, list):
            images = [img.get("url", "") if isinstance(img, dict) else str(img) for img in images_raw[:5]]

        location = str(raw.get("location", "") or raw.get("country", ""))
        condition = str(raw.get("condition", "") or raw.get("item_condition", ""))
        badge = str(raw.get("badge", "") or "")
        seller_raw = raw.get("seller", {}) or {}
        seller_id = str(seller_raw.get("id", "")) if isinstance(seller_raw, dict) else ""
        created_at = str(raw.get("created_at", "") or raw.get("listing_time", ""))
        status = str(raw.get("status", "") or "")
        username = str(seller_raw.get("username", "")) if isinstance(seller_raw, dict) else ""
        description = str(raw.get("description", "") or "")

        url = raw.get("url", "") or f"https://www.carousell.sg/p/{item_id}"

        return GoofishItem(
            item_id=item_id,
            title=title,
            price_cny=price,
            url=url,
            condition=condition,
            location=location,
            badge=badge,
            images=images,
            seller_id=seller_id or username,
            status=status,
            created_at=created_at,
            description=description,
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
        query,
        count=criteria.limit,
        country=DEFAULT_COUNTRY,
        sort=3,
        price_min=price_min,
        price_max=price_max,
    )

    if not raw_items:
        return SearchResult(empty=True)

    parsed = [_carousell_item_to_model(i) for i in raw_items]
    parsed = [i for i in parsed if i is not None and i.price_cny > 0]

    return SearchResult(items=parsed, empty=len(parsed) == 0)


async def search_by_brand_type(
    brand: str,
    item_type: str,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    limit: int = 50,
) -> SearchResult:
    criteria = SearchCriteria(
        brand=brand,
        item_type=item_type,
        price_min_cny=price_min,
        price_max_cny=price_max,
        limit=limit,
    )
    return await search_items(criteria)
