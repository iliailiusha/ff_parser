from typing import Optional

from goofish_parser.scraper.models import GoofishItem, MarketPrice, ScoredItem


def _rate() -> float:
    from goofish_parser.services.exchange_rate import get_cny_to_rub
    return get_cny_to_rub()


def score_item(item: GoofishItem, market: MarketPrice) -> Optional[ScoredItem]:
    if market.avg_price_cny <= 0 or item.price_cny <= 0:
        return None

    discount_pct = round((1 - item.price_cny / market.avg_price_cny) * 100, 1)
    rate = _rate()

    return ScoredItem(
        item=item,
        market_avg_cny=market.avg_price_cny,
        discount_pct=discount_pct,
        price_rub=round(item.price_cny * rate, 0),
        market_avg_rub=round(market.avg_price_cny * rate, 0),
        score=discount_pct,
    )


def score_items(items: list[GoofishItem], market: Optional[MarketPrice] = None) -> list[ScoredItem]:
    if not items:
        return []

    if market is None:
        from goofish_parser.analyzer.market import calculate_market_price
        market = calculate_market_price(items)

    if market is None:
        return []

    scored = []
    for item in items:
        s = score_item(item, market)
        if s:
            scored.append(s)

    scored.sort(key=lambda x: x.discount_pct, reverse=True)
    return scored
