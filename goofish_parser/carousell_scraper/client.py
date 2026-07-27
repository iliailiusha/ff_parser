import logging
from typing import Any, Optional

from goofish_parser.carousell_scraper.browser_auth import search_carousell_pw

logger = logging.getLogger(__name__)

CAROUSELL_COUNTRIES = {
    "SG": {"currency": "SGD", "name": "Singapore"},
    "MY": {"currency": "MYR", "name": "Malaysia"},
    "PH": {"currency": "PHP", "name": "Philippines"},
    "ID": {"currency": "IDR", "name": "Indonesia"},
    "HK": {"currency": "HKD", "name": "Hong Kong"},
    "TW": {"currency": "TWD", "name": "Taiwan"},
}

DEFAULT_COUNTRY = "SG"


async def search_carousell(
    query: str,
    count: int = 50,
    country: str = DEFAULT_COUNTRY,
    sort: int = 3,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
) -> list[dict]:
    logger.info(
        "Carousell search: query='%s', count=%d, country=%s",
        query, count, country,
    )

    items = await search_carousell_pw(
        query=query,
        count=count,
        country=country,
        sort=sort,
        price_min=price_min,
        price_max=price_max,
    )

    logger.info(
        "Carousell search complete: %d items for query='%s'",
        len(items), query,
    )
    return items
