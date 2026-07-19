from pydantic import BaseModel, field_validator
from typing import Optional


class SearchInput(BaseModel):
    brand: str
    item_type: str = ""
    model: str = ""
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    price_currency: str = "KRW"
    limit: int = 50

    @field_validator("brand", "item_type", "model")
    @classmethod
    def sanitize_text(cls, v: str) -> str:
        if not v:
            return ""
        v = v.strip()[:100]
        return v.replace("*", "").replace("_", "").replace("`", "").replace("[", "").replace("]", "")

    @field_validator("price_min", "price_max")
    @classmethod
    def validate_price(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (v < 0 or v > 10_000_000):
            raise ValueError("Price out of range (0-10,000,000)")
        return v

    @field_validator("price_currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        allowed = {"KRW", "JPY", "SGD", "CNY", "RUB"}
        v = v.upper()
        if v not in allowed:
            raise ValueError(f"Currency must be one of {allowed}")
        return v

    @field_validator("limit")
    @classmethod
    def validate_limit(cls, v: int) -> int:
        return max(1, min(v, 200))


class SettingsInput(BaseModel):
    platform: str
    action: str

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        allowed = {"fruitsfamily", "bunjang", "carousell", "mercari_jp", "goofish"}
        if v not in allowed:
            raise ValueError(f"Platform must be one of {allowed}")
        return v

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v not in {"enable", "disable", "toggle"}:
            raise ValueError("Action must be enable/disable/toggle")
        return v


class FindInput(BaseModel):
    query: str

    @field_validator("query")
    @classmethod
    def sanitize_query(cls, v: str) -> str:
        v = v.strip()[:200]
        return v.replace("*", "").replace("_", "").replace("`", "").replace("[", "").replace("]", "")