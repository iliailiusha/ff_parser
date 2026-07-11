import logging
from typing import Any, Optional

from goofish_parser.scraper.models import GoofishItem, SearchCriteria, SearchResult, PLATFORM_INFO
from goofish_parser.mercari_jp_scraper.client import search_mercari_jp

logger = logging.getLogger(__name__)


def _parse_price_jpy(val: Any) -> float:
    try:
        return float(str(val).replace(",", "").replace("¥", "").strip())
    except (ValueError, AttributeError):
        return 0.0


def _mercari_item_to_model(raw: dict) -> Optional[GoofishItem]:
    try:
        item_id = str(raw.get("id", ""))
        title = str(raw.get("name", "") or raw.get("title", ""))
        price = _parse_price_jpy(raw.get("price", 0))

        photos = raw.get("photos", []) or raw.get("images", []) or raw.get("thumbnailUrls", [])
        images = []
        if photos:
            for p in photos[:5]:
                if isinstance(p, dict):
                    images.append(p.get("url", "") or p.get("thumbnailUrl", ""))
                elif isinstance(p, str):
                    images.append(p)

        status = str(raw.get("status", "") or "")
        created_at_str = str(raw.get("created_at", "") or raw.get("listingTime", "") or raw.get("listing_time", ""))
        if created_at_str and created_at_str.isdigit():
            from datetime import datetime
            created_at_str = datetime.fromtimestamp(int(created_at_str)).isoformat()

        condition_map = {
            "1": "新品、未使用",
            "2": "未使用に近い",
            "3": "目立った傷や汚れなし",
            "4": "やや傷や汚れあり",
            "5": "傷や汚れあり",
            "6": "全体的に状態が悪い",
        }
        condition_id = str(raw.get("item_condition_id", "") or raw.get("conditionId", "") or raw.get("condition", ""))
        condition = condition_map.get(condition_id, "")

        seller_raw = raw.get("seller", {})
        seller_id = str(seller_raw.get("id", "")) if isinstance(seller_raw, dict) else ""

        item_url = raw.get("item_url", "") or raw.get("url", "")
        if not item_url and item_id:
            item_url = f"https://jp.mercari.com/item/{item_id}"

        return GoofishItem(
            item_id=item_id,
            title=title,
            price_cny=price,
            url=item_url,
            condition=condition,
            location="",
            badge="",
            images=images,
            seller_id=seller_id,
            status=status,
            created_at=created_at_str,
            source="mercari_jp",
            country=PLATFORM_INFO["mercari_jp"]["country"],
            currency=PLATFORM_INFO["mercari_jp"]["currency"],
            seller_extra_1h=0,
        )
    except Exception:
        logger.exception("Failed to parse Mercari JP item")
        return None


async def search_items(criteria: SearchCriteria) -> SearchResult:
    query_parts = [criteria.brand]
    if criteria.item_type:
        query_parts.append(criteria.item_type)
    query = " ".join(query_parts)

    price_min = int(criteria.price_min_cny) if criteria.price_min_cny is not None else None
    price_max = int(criteria.price_max_cny) if criteria.price_max_cny is not None else None

    raw_items = await search_mercari_jp(
        query,
        limit=criteria.limit,
        price_min=price_min,
        price_max=price_max,
    )

    if not raw_items:
        return SearchResult(empty=True)

    parsed = [_mercari_item_to_model(i) for i in raw_items]
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
