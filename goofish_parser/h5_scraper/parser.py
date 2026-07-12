import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)


@dataclass
class H5ItemData:
    """Нормализованные данные о товаре с H5-страницы."""

    item_id: str = ""
    title: str = ""
    price_cny: float = 0.0
    original_price_cny: float = 0.0
    description: str = ""
    images: list[str] = field(default_factory=list)
    seller_name: str = ""
    seller_id: str = ""
    condition: str = ""
    location: str = ""
    url: str = ""
    raw_json: Optional[dict] = None


# ── паттерны для поиска JSON-блоков в <script> ────────────

_RE_INITIAL_DATA = re.compile(
    r"window\.__INITIAL_DATA__\s*=\s*(\{.+?\});",
    re.DOTALL,
)
_RE_NUXT = re.compile(
    r"window\.__NUXT__\s*=\s*(\{.+?\});",
    re.DOTALL,
)
_RE_INITIAL_STATE = re.compile(
    r"window\.__INITIAL_STATE__\s*=\s*(\{.+?\});",
    re.DOTALL,
)
_RE_PAGE_DATA = re.compile(
    r"window\.__pageData__\s*=\s*(\{.+?\});",
    re.DOTALL,
)
_RE_JSON_LD = re.compile(
    r'<script\s+type="application/ld\+json">(.+?)</script>',
    re.DOTALL,
)


def _clean_json(raw: str) -> str:
    """Очищает JSON от неэкранированных управляющих символов."""
    raw = re.sub(r"\\'", "'", raw)
    raw = re.sub(r"\\\n", " ", raw)
    raw = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), raw)
    return raw


def _extract_json_blocks(html: str) -> list[dict]:
    """Ищет все JSON-объекты внутри <script>-тегов по известным именам переменных."""
    candidates = []
    for pattern in (_RE_INITIAL_DATA, _RE_NUXT, _RE_INITIAL_STATE, _RE_PAGE_DATA):
        for match in pattern.finditer(html):
            raw = _clean_json(match.group(1))
            try:
                candidates.append(json.loads(raw))
            except json.JSONDecodeError as exc:
                logger.debug("JSON decode error for %s: %s", pattern.pattern[:30], exc)

    for match in _RE_JSON_LD.finditer(html):
        try:
            candidates.append(json.loads(match.group(1)))
        except json.JSONDecodeError:
            pass

    return candidates


def _extract_title(soup: BeautifulSoup, fallback: str = "") -> str:
    meta = soup.find("meta", property="og:title")
    if meta and meta.get("content"):
        return meta["content"].strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    title_tag = soup.find("title")
    if title_tag:
        return title_tag.get_text(strip=True)
    return fallback


def _extract_price(soup: BeautifulSoup) -> float:
    price_selectors = [
        "span.price",
        "div.price",
        "span[class*=price]",
        "div[class*=price]",
        "span.trade-price",
        "span[class*=Price]",
        "[class*=current-price]",
        "[class*=discount-price]",
    ]
    for sel in price_selectors:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(strip=True).replace("¥", "").replace(",", "")
            try:
                return float(text)
            except ValueError:
                continue
    meta = soup.find("meta", property="product:price:amount")
    if meta and meta.get("content"):
        try:
            return float(meta["content"])
        except ValueError:
            pass
    return 0.0


def _extract_images(soup: BeautifulSoup) -> list[str]:
    urls: list[str] = []
    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        urls.append(og_image["content"])

    for img in soup.select("img[src*='alicdn'], img[src*='taobaocdn'], img[data-src*='alicdn']"):
        src = img.get("src") or img.get("data-src") or ""
        if src and src not in urls:
            urls.append(src)
            if len(urls) >= 10:
                break

    gallery = soup.select("[class*=gallery] img, [class*=preview] img, [class*=swiper] img")
    for img in gallery:
        src = img.get("src") or img.get("data-src") or ""
        if src and src.startswith("http") and src not in urls:
            urls.append(src)
            if len(urls) >= 10:
                break

    return urls


def _extract_price_from_json(data: dict) -> float:
    """Рекурсивно ищет цену в JSON любой вложенности."""
    price_keys = ("price", "sellPrice", "itemPrice", "finalPrice",
                  "currentPrice", "discountPrice", "priceCny", "priceYuan")
    stack = [data]
    visited = set()
    results: list[float] = []
    while stack:
        node = stack.pop()
        node_id = id(node)
        if node_id in visited:
            continue
        visited.add(node_id)
        if not isinstance(node, dict):
            continue
        for key in price_keys:
            val = node.get(key)
            if isinstance(val, (int, float)):
                results.append(float(val))
            elif isinstance(val, str):
                cleaned = val.replace(",", "").replace("¥", "").replace("$", "").strip()
                try:
                    results.append(float(cleaned))
                except ValueError:
                    pass
        for v in node.values():
            if isinstance(v, dict):
                stack.append(v)
            elif isinstance(v, list):
                stack.extend(item for item in v if isinstance(item, dict))
    return results[0] if results else 0.0


def _find_in_nested(data: dict, *keys: str) -> str:
    """Рекурсивно ищет ключи в JSON любой вложенности."""
    stack = [data]
    visited = set()
    while stack:
        node = stack.pop()
        node_id = id(node)
        if node_id in visited:
            continue
        visited.add(node_id)
        if not isinstance(node, dict):
            continue
        for key in keys:
            val = node.get(key)
            if val is not None:
                if isinstance(val, str):
                    return val
                if isinstance(val, (int, float)):
                    return str(val)
                if isinstance(val, list):
                    items = [str(v) for v in val if isinstance(v, (str, int, float))]
                    if items:
                        return " ".join(items)
        for v in node.values():
            if isinstance(v, (dict, list)):
                if isinstance(v, list):
                    stack.extend(item for item in v if isinstance(item, dict))
                else:
                    stack.append(v)
    return ""


def _extract_images_from_json(data: dict) -> list[str]:
    """Рекурсивно ищет списки URL изображений в JSON."""
    image_keys = ("images", "imageUrls", "pictures", "imgUrls", "imageList", "picUrls")
    stack = [data]
    visited = set()
    results: list[str] = []
    while stack and len(results) < 10:
        node = stack.pop()
        node_id = id(node)
        if node_id in visited:
            continue
        visited.add(node_id)
        if not isinstance(node, dict):
            continue
        for key in image_keys:
            val = node.get(key)
            if isinstance(val, list):
                for v in val:
                    if isinstance(v, str) and v.startswith(("http://", "https://")) and v not in results:
                        results.append(v)
                    elif isinstance(v, dict):
                        for sub_key in ("url", "src", "fullUrl", "original"):
                            sub = v.get(sub_key)
                            if isinstance(sub, str) and sub.startswith(("http://", "https://")) and sub not in results:
                                results.append(sub)
        for v in node.values():
            if isinstance(v, dict):
                stack.append(v)
            elif isinstance(v, list):
                stack.extend(item for item in v if isinstance(item, dict))
    return results


def parse_h5_page(html: str, url: str = "") -> H5ItemData:
    """Парсит HTML H5-страницы Goofish и возвращает структурированные данные.

    Стратегия:
      1. Ищем JSON-блоки в <script>-тегах (window.__INITIAL_DATA__, etc.)
         и пытаемся извлечь цену, заголовок, картинки из них.
      2. Если JSON не дал полных данных — парсим DOM через BeautifulSoup.
    """
    soup = BeautifulSoup(html, "lxml")
    item = H5ItemData(url=url)

    json_blocks = _extract_json_blocks(html)

    # Пытаемся извлечь item_id из URL
    id_match = re.search(r"[?&]id=(\d+)", url)
    if id_match:
        item.item_id = id_match.group(1)
    id_match2 = re.search(r"/(\d{10,})", url)
    if id_match2:
        item.item_id = id_match2.group(1)

    # ── парсинг из JSON ─────────────────────────────────────
    for data in json_blocks:
        if not item.item_id:
            candidate = _find_in_nested(data, "itemId", "item_id", "id", "itemIdStr")
            if candidate:
                item.item_id = candidate

        if not item.title:
            title_v = _find_in_nested(
                data, "title", "itemTitle", "itemName", "name", "subject",
            )
            if title_v:
                item.title = title_v

        if not item.price_cny:
            item.price_cny = _extract_price_from_json(data)

        if not item.original_price_cny:
            orig = _find_in_nested(
                data, "originPrice", "originalPrice", "priceBeforeDiscount",
            )
            if orig:
                try:
                    item.original_price_cny = float(
                        orig.replace(",", "").replace("¥", "").strip()
                    )
                except ValueError:
                    pass

        if not item.description:
            desc_v = _find_in_nested(
                data, "description", "itemDesc", "detail", "desc",
            )
            if desc_v:
                item.description = desc_v

        if not item.images:
            item.images = _extract_images_from_json(data)

        if not item.seller_name:
            seller = _find_in_nested(data, "sellerName", "nick", "seller", "userName")
            if seller:
                item.seller_name = seller

        if not item.seller_id:
            sid = _find_in_nested(data, "sellerId", "userId", "seller_id")
            if sid:
                item.seller_id = sid

        if not item.location:
            loc = _find_in_nested(data, "location", "city", "province")
            if loc:
                item.location = loc

        if not item.condition:
            cond = _find_in_nested(data, "condition", "itemCondition", "quality")
            if cond:
                item.condition = cond

        if item.title and item.price_cny > 0:
            item.raw_json = data
            break

    # ── парсинг из DOM (fallback) ───────────────────────────
    if not item.title:
        item.title = _extract_title(soup)

    if not item.price_cny or item.price_cny == 0.0:
        item.price_cny = _extract_price(soup)

    if not item.images:
        item.images = _extract_images(soup)

    if not item.item_id and not url:
        # последняя попытка — og:url
        og_url = soup.find("meta", property="og:url")
        if og_url and og_url.get("content"):
            m = re.search(r"id=(\d+)", og_url["content"])
            if m:
                item.item_id = m.group(1)

    logger.info(
        "Parsed item — id=%s title=%s price=%.2f images=%d",
        item.item_id or "?",
        item.title[:40] if item.title else "?",
        item.price_cny,
        len(item.images),
    )
    return item
