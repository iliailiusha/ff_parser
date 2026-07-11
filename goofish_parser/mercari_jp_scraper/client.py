import json
import logging
import re
import time
from typing import Any, Optional

from curl_cffi.requests import AsyncSession

logger = logging.getLogger(__name__)

SEARCH_PAGE = "https://jp.mercari.com/search"


async def search_mercari_jp(
    query: str,
    limit: int = 50,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    sort: str = "created_time",
    order: str = "desc",
) -> list[dict]:
    async with AsyncSession() as session:
        try:
            await session.get(
                "https://jp.mercari.com/",
                headers={
                    "Accept": "text/html",
                    "Accept-Language": "ja,en;q=0.9",
                },
                impersonate="chrome124",
                timeout=30,
            )
        except Exception:
            pass

        try:
            params = {"keyword": query}
            if price_min is not None:
                params["price_min"] = price_min
            if price_max is not None:
                params["price_max"] = price_max

            resp = await session.get(
                SEARCH_PAGE,
                params=params,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "ja,en;q=0.9",
                    "Referer": "https://jp.mercari.com/",
                },
                impersonate="chrome124",
                timeout=30,
            )
            resp.raise_for_status()
            html = resp.text
        except Exception as e:
            logger.error(f"Mercari JP search page error: {e}")
            return []

        items = _extract_from_html(html)
        logger.info(f"Mercari JP found {len(items)} items")
        return items


def _extract_from_html(html: str) -> list[dict]:
    items = []

    next_data = _extract_next_data(html)
    if next_data:
        items = _parse_next_data_items(next_data)
        if items:
            logger.info("Mercari JP: extracted items from __NEXT_DATA__")
            return items

    items = _extract_from_jsonld(html)
    if items:
        logger.info(f"Mercari JP: extracted {len(items)} items from JSON-LD")
        return items

    items = _extract_regex_fallback(html)
    return items


def _extract_next_data(html: str) -> Optional[dict]:
    patterns = [
        r'<script[^>]*id="__NEXT_DATA__"[^>]*type="application/json"[^>]*>(.*?)</script>',
        r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
    return None


def _parse_next_data_items(data: dict) -> list[dict]:
    try:
        props = data.get("props", {}) or {}
        page_props = props.get("pageProps", {}) or {}
    except AttributeError:
        return []

    candidates = []
    for key in ["items", "searchResult", "products", "initialState", "item"]:
        val = page_props.get(key)
        if val is not None:
            candidates.append(val)

    for candidate in candidates:
        if isinstance(candidate, dict):
            for sub_key in ["items", "products", "result"]:
                sub_val = candidate.get(sub_key)
                if isinstance(sub_val, list) and sub_val:
                    return sub_val
        elif isinstance(candidate, list):
            return candidate

    try:
        state = page_props.get("initialState", {})
        if isinstance(state, dict):
            items = state.get("items", []) or state.get("products", [])
            if items:
                return items
            for maybe_list in state.values():
                if isinstance(maybe_list, list) and len(maybe_list) > 0 and isinstance(maybe_list[0], dict) and "id" in maybe_list[0]:
                    return maybe_list
    except Exception:
        pass

    return []


def _extract_from_jsonld(html: str) -> list[dict]:
    pattern = r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
    items = []
    for match in re.finditer(pattern, html, re.DOTALL):
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            data = [data]
        for entry in data:
            if isinstance(entry, dict) and entry.get("name") and entry.get("offers"):
                try:
                    price = float(entry["offers"].get("price", 0))
                except (ValueError, TypeError):
                    price = 0
                if price > 0:
                    img = ""
                    if entry.get("image"):
                        img = entry["image"][0] if isinstance(entry["image"], list) else entry["image"]
                    items.append({
                        "id": entry.get("sku", "") or str(hash(entry.get("name", ""))),
                        "name": entry.get("name", ""),
                        "price": int(price),
                        "photos": [{"url": img}] if img else [],
                        "url": entry.get("url", ""),
                        "item_url": entry.get("url", ""),
                        "status": "on_sale",
                    })
    return items


def _extract_regex_fallback(html: str) -> list[dict]:
    items = []
    seen_ids = set()

    item_card_pattern = re.compile(
        r'<a[^>]*href=["\'](/item/([^"\']+))["\'][^>]*>.*?'
        r'<img[^>]*src=["\']([^"\']+)["\'][^>]*>.*?'
        r'(?:alt|title)=["\']([^"\']*)["\'].*?'
        r'¥\s*([0-9,]+)',
        re.DOTALL,
    )

    for match in item_card_pattern.finditer(html):
        item_url = match.group(1)
        item_id = match.group(2)
        img_url = match.group(3)
        name = match.group(4).strip()
        price_str = match.group(5).replace(",", "")

        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)

        try:
            price = int(price_str)
        except ValueError:
            price = 0

        items.append({
            "id": item_id,
            "name": name,
            "price": price,
            "photos": [{"url": img_url}] if img_url else [],
            "item_url": f"https://jp.mercari.com{item_url}",
            "url": f"https://jp.mercari.com{item_url}",
            "status": "on_sale",
        })

    return items
