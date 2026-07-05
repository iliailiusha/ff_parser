from pydantic import BaseModel
from typing import Optional


class GoofishItem(BaseModel):
    item_id: str
    title: str
    price_cny: float
    url: str
    condition: str = ""
    location: str = ""
    badge: str = ""
    images: list[str] = []
    seller_id: str = ""
    category_id: str = ""


class SearchCriteria(BaseModel):
    brand: str
    item_type: str
    price_min_cny: Optional[float] = None
    price_max_cny: Optional[float] = None
    limit: int = 30


class MarketPrice(BaseModel):
    brand: str
    item_type: str
    avg_price_cny: float
    median_price_cny: float
    min_price_cny: float
    max_price_cny: float
    sample_count: int


class ScoredItem(BaseModel):
    item: GoofishItem
    market_avg_cny: float
    discount_pct: float
    price_rub: float
    market_avg_rub: float
    score: float

    @property
    def is_deal(self) -> bool:
        return self.discount_pct > 10
