from pydantic import BaseModel, field_validator
from typing import Optional


PLATFORM_INFO = {
    "fruitsfamily": {"name": "FruitsFamily", "country": "🇰🇷 Корея", "currency": "₩", "url": "https://fruitsfamily.com"},
    "bunjang": {"name": "Bunjang", "country": "🇰🇷 Корея", "currency": "₩", "url": "https://bunjang.co.kr"},
    "carousell": {"name": "Carousell", "country": "🇸🇬 Сингапур", "currency": "SGD", "url": "https://www.carousell.sg"},
    "mercari_jp": {"name": "Mercari JP", "country": "🇯🇵 Япония", "currency": "¥", "url": "https://jp.mercari.com"},
}

COUNTRY_PLATFORMS = {
    "🇰🇷 Корея": ["fruitsfamily", "bunjang"],
    "🇸🇬 Сингапур": ["carousell"],
    "🇯🇵 Япония": ["mercari_jp"],
}

ALL_PLATFORMS = sorted(PLATFORM_INFO.keys())


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
    price_original_cny: float = 0.0
    discount_rate: Optional[float] = None
    is_liked: bool = False
    like_count: int = 0
    size: str = ""
    created_at: str = ""
    status: str = ""
    is_visible: bool = True
    seller_extra_1h: int = 0
    source: str = "fruitsfamily"
    country: str = "🇰🇷 Корея"
    currency: str = "₩"
    alt_sources: list[str] = []
    alt_urls: list[str] = []

    @field_validator("location", "condition", "size", "status", mode="before")
    @classmethod
    def _stringify_none(cls, v):
        return "" if v is None else v


class SearchCriteria(BaseModel):
    brand: str
    item_type: str
    price_min_cny: Optional[float] = None
    price_max_cny: Optional[float] = None
    limit: int = 30


class SearchResult(BaseModel):
    items: list[GoofishItem] = []
    requires_auth: bool = False
    blocked: bool = False
    empty: bool = False
    error: str = ""


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
