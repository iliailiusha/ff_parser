import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

RSC_PUSH_RE = re.compile(
    r'self\.__next_f\.push\(\[[^,]*,\s*"((?:[^"\\]|\\.)*)"\]\)',
)

JSON_PAYLOAD_RE = re.compile(r'^\d+:\s*(\{.*)$')

JPY_PRICE_RE = re.compile(r'[¥￥]\s*(\d[\d,]*)|(\d[\d,]*)\s*円')

ITEM_CANDIDATE_RE = re.compile(
    r'(?:item|product|listing|mercari)',
    re.IGNORECASE,
)


def extract_rsc_chunks(html: str) -> list[str]:
    chunks: list[str] = []
    for match in RSC_PUSH_RE.finditer(html):
        raw = match.group(1)
        try:
            decoded = raw.encode("utf-8").decode("unicode_escape")
            chunks.append(decoded)
        except Exception:
            chunks.append(raw)
    logger.debug("Extracted %d RSC chunks", len(chunks))
    return chunks


def _try_parse_json(data_str: str) -> Optional[Any]:
    try:
        return json.loads(data_str)
    except json.JSONDecodeError:
        return None


def _walk_for_items(
    obj: Any,
    depth: int = 0,
    max_depth: int = 20,
) -> list[dict]:
    if depth > max_depth:
        return []
    if not isinstance(obj, (dict, list)):
        return []

    found: list[dict] = []
    items: list[dict] = []

    if isinstance(obj, dict):
        has_name = bool(obj.get("name") or obj.get("title"))
        has_price = bool(obj.get("price") is not None)
        has_id = bool(obj.get("id"))
        has_thumbnails = bool(obj.get("thumbnails") or obj.get("photos") or obj.get("images"))

        if has_name and has_price and (has_id or has_thumbnails):
            candidate = {
                "id": str(obj.get("id", "")),
                "name": str(obj.get("name", "") or obj.get("title", "")),
                "price": _extract_price(obj.get("price", 0)),
                "photos": obj.get("thumbnails", []) or obj.get("photos", []) or obj.get("images", []),
                "item_url": f"https://jp.mercari.com/item/{obj.get('id', '')}",
                "status": "STATUS_ON_SALE",
                "created": 0,
                "brand": "",
                "description": "",
            }
            if candidate["name"] and len(candidate["name"]) > 3:
                found.append(candidate)

        for val in obj.values():
            items.extend(_walk_for_items(val, depth + 1, max_depth))
    else:
        for val in obj:
            items.extend(_walk_for_items(val, depth + 1, max_depth))

    return found or items


def _extract_price(price: Any) -> int:
    if isinstance(price, (int, float)):
        return int(price)
    if isinstance(price, str):
        cleaned = re.sub(r"[^\d]", "", price)
        try:
            return int(cleaned)
        except ValueError:
            pass
    if isinstance(price, dict):
        return _extract_price(price.get("amount", 0))
    return 0


def parse_rsc_items(html: str) -> list[dict]:
    chunks = extract_rsc_chunks(html)
    if not chunks:
        logger.warning("No RSC chunks found in HTML")
        return []

    all_items: list[dict] = []
    seen_ids: set[str] = set()

    for chunk in chunks:
        payload_match = re.match(r"^\d+:\s*(.*)", chunk)
        if not payload_match:
            continue

        payload_str = payload_match.group(1)

        if payload_str.startswith("{"):
            parsed = _try_parse_json(payload_str)
            if parsed:
                items = _walk_for_items(parsed)
                for item in items:
                    item_id = item.get("id", "")
                    if item_id and item_id not in seen_ids:
                        seen_ids.add(item_id)
                        all_items.append(item)

    if not all_items:
        logger.debug("RSC parsing found 0 items via JSON walk, trying price pattern")
        all_items = _extract_from_plain_text(chunks)

    logger.info("RSC parser: found %d unique items", len(all_items))
    return all_items


def _extract_from_plain_text(chunks: list[str]) -> list[dict]:
    full_text = " ".join(chunks)
    lines = full_text.split("\\n")

    items: list[dict] = []
    current_name = ""
    current_price = 0

    for line in lines:
        clean = line.strip().strip('"')

        price_match = JPY_PRICE_RE.search(clean)
        if price_match:
            price_str = price_match.group(1) or price_match.group(2) or ""
            price = int(re.sub(r"[^\d]", "", price_str)) if price_str else 0

            if current_name and price > 0:
                m = re.search(r"m(\d+)", clean)
                item_id = f"m{m.group(1)}" if m else ""
                items.append({
                    "id": item_id,
                    "name": current_name,
                    "price": price,
                    "photos": [],
                    "item_url": f"https://jp.mercari.com/item/{item_id}" if item_id else "",
                    "status": "STATUS_ON_SALE",
                    "created": 0,
                    "brand": "",
                    "description": "",
                })
                current_name = ""
                current_price = 0

        if re.match(r"^[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\w\s\-&,\/()]{5,80}$", clean):
            has_item_kw = bool(re.search(r"(item|product|listing)", clean, re.IGNORECASE))
            has_brand = bool(re.search(r"(nike|adidas|jordan|gucci|prada|uniqlo)", clean, re.IGNORECASE))
            if has_item_kw or has_brand or len(clean) > 15:
                current_name = clean

    return items
