import logging
from typing import Any, Optional

from goofish_parser.scraper.models import GoofishItem, SearchCriteria, SearchResult, PLATFORM_INFO
from goofish_parser.bunjang_scraper.client import search_bunjang

logger = logging.getLogger(__name__)


def _parse_price_krw(price_val: Any) -> float:
    try:
        return float(str(price_val).replace(",", "").replace("₩", "").replace("원", "").strip())
    except (ValueError, AttributeError):
        return 0.0


def _bunjang_item_to_model(raw: dict) -> Optional[GoofishItem]:
    try:
        item_id = str(raw.get("pid", ""))
        title = str(raw.get("name") or "")
        price = _parse_price_krw(raw.get("price", 0))
        location = str(raw.get("region", "") or "")
        status = str(raw.get("status", "") or "")
        condition_map = {"0": "중고", "1": "새제품", "2": "리퍼"}
        condition = condition_map.get(str(raw.get("condition", "")), "")
        seller_id = str(raw.get("uid", "") or "")
        images_raw = raw.get("image", "")
        images = []
        if images_raw:
            if isinstance(images_raw, str):
                images = [images_raw]
            elif isinstance(images_raw, list):
                images = images_raw
        badge = str(raw.get("badge", "") or "")
        created_at_timestamp = raw.get("update_time", 0) or raw.get("reg_time", 0)
        created_at = ""
        if created_at_timestamp:
            from datetime import datetime
            created_at = datetime.fromtimestamp(int(created_at_timestamp)).isoformat()

        url = f"https://m.bunjang.co.kr/products/{item_id}"

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
            source="bunjang",
            country=PLATFORM_INFO["bunjang"]["country"],
            currency=PLATFORM_INFO["bunjang"]["currency"],
            seller_extra_1h=0,
        )
    except Exception:
        logger.exception("Failed to parse Bunjang item")
        return None


async def search_items(criteria: SearchCriteria) -> SearchResult:
    query_parts = [criteria.brand]
    if criteria.item_type:
        query_parts.append(criteria.item_type)
    query = " ".join(query_parts)

    price_min = int(criteria.price_min_cny) if criteria.price_min_cny is not None else None
    price_max = int(criteria.price_max_cny) if criteria.price_max_cny is not None else None

    raw_items = await search_bunjang(
        query, max_page=10, per_page=100,
        price_min=price_min, price_max=price_max,
    )

    if not raw_items:
        return SearchResult(empty=True)

    parsed = [_bunjang_item_to_model(i) for i in raw_items]
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
