import statistics
from typing import Optional

from goofish_parser.scraper.models import GoofishItem, MarketPrice


def calculate_market_price(items: list[GoofishItem]) -> Optional[MarketPrice]:
    if not items:
        return None

    prices = [item.price_cny for item in items if item.price_cny > 0]
    if not prices:
        return None

    prices.sort()

    return MarketPrice(
        brand=items[0].title.split()[0] if items[0].title else "",
        item_type="",
        avg_price_cny=round(statistics.mean(prices), 2),
        median_price_cny=round(statistics.median(prices), 2),
        min_price_cny=prices[0],
        max_price_cny=prices[-1],
        sample_count=len(prices),
    )


def get_price_percentile(items: list[GoofishItem], percentile: float = 25.0) -> float:
    prices = [item.price_cny for item in items if item.price_cny > 0]
    if not prices:
        return 0.0
    prices.sort()
    idx = max(0, int(len(prices) * percentile / 100))
    return prices[idx]
