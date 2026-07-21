import json
import logging
import uuid
from base64 import urlsafe_b64encode
from time import time as now
from typing import Any, Optional

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from goofish_parser.services.user_agent import get_random_ua

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.mercari.jp/v2/entities:search"


def _int_to_bytes(n: int) -> bytes:
    return n.to_bytes((n.bit_length() + 7) // 8, byteorder="big")


def _b64url(data: bytes) -> str:
    return urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _generate_dpop(*, uuid: str, method: str, url: str) -> str:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    pub_nums = public_key.public_numbers()

    header = {
        "typ": "dpop+jwt",
        "alg": "ES256",
        "jwk": {
            "crv": "P-256",
            "kty": "EC",
            "x": _b64url(_int_to_bytes(pub_nums.x)),
            "y": _b64url(_int_to_bytes(pub_nums.y)),
        },
    }

    payload = {
        "iat": int(now()),
        "jti": uuid,
        "htu": url,
        "htm": method.upper(),
    }

    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    data_to_sign = f"{header_b64}.{payload_b64}".encode()

    signature = private_key.sign(data_to_sign, ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(signature)
    sig_b64 = _b64url(_int_to_bytes(r) + _int_to_bytes(s))

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def _convert_booleans(obj: Any) -> Any:
    if isinstance(obj, bool):
        return str(obj).lower()
    if isinstance(obj, dict):
        return {k: _convert_booleans(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_convert_booleans(i) for i in obj]
    return obj


async def search_mercari_jp(
    query: str,
    limit: int = 500,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    sort: str = "SORT_CREATED_TIME",
    order: str = "ORDER_DESC",
) -> list[dict]:
    page_size = 120
    session_id = f"MERCARI_BOT_{uuid.uuid4()}"

    payload: dict[str, Any] = {
        "userId": f"MERCARI_BOT_{uuid.uuid4()}",
        "pageSize": page_size,
        "pageToken": "v1:0",
        "searchSessionId": session_id,
        "indexRouting": "INDEX_ROUTING_UNSPECIFIED",
        "searchCondition": {
            "keyword": query,
            "sort": sort,
            "order": order,
            "status": ["STATUS_ON_SALE"],
            "excludeKeyword": "",
        },
        "withAuction": True,
        "defaultDatasets": ["DATASET_TYPE_MERCARI", "DATASET_TYPE_BEYOND"],
    }

    if price_min is not None:
        payload["searchCondition"]["priceMin"] = price_min
    if price_max is not None:
        payload["searchCondition"]["priceMax"] = price_max

    all_items: list[dict] = []
    max_pages = 10

    headers = {
        "X-Platform": "web",
        "Accept": "*/*",
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": get_random_ua(),
    }

    async with httpx.AsyncClient(timeout=30) as client:
        for _ in range(max_pages):
            if len(all_items) >= limit:
                break

            dpop = _generate_dpop(
                uuid=str(uuid.uuid4()),
                method="POST",
                url=SEARCH_URL,
            )
            headers["DPoP"] = dpop
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

            try:
                resp = await client.post(
                    SEARCH_URL,
                    content=body,
                    headers=headers,
                )
                logger.debug(f"Mercari API response status={resp.status_code} body={resp.text[:500]}")
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f"Mercari JP API error: {e}")
                break

            items = data.get("items", [])
            if not items:
                logger.debug(f"Mercari response data: {json.dumps(data, ensure_ascii=False)[:300]}")
                break

            for item in items:
                all_items.append(_remap_item(item))
                if len(all_items) >= limit:
                    break

            next_token = data.get("meta", {}).get("nextPageToken")
            if not next_token:
                break
            payload["pageToken"] = next_token

    logger.info(f"Mercari JP API found {len(all_items)} items")
    return all_items


def _remap_item(item: dict) -> dict:
    item_id = item.get("id", "")
    # All Mercari JP items use /item/ URL format
    item_url = f"https://jp.mercari.com/item/{item_id}"
    logger.debug(f"Remapped Mercari item: id={item_id} url={item_url}")
    brand_raw = item.get("itemBrand") or item.get("brand")
    brand_name = ""
    if isinstance(brand_raw, dict):
        brand_name = brand_raw.get("name", "")
    elif isinstance(brand_raw, str):
        brand_name = brand_raw
    elif brand_raw is None:
        brand_name = ""
    return {
        "id": item_id,
        "name": item.get("name", ""),
        "price": item.get("price", 0),
        "photos": item.get("thumbnails", []),
        "status": item.get("status", ""),
        "created": item.get("created", 0),
        "updated": item.get("updated", 0),
        "item_url": item_url,
        "brand": brand_name,
        "description": item.get("description") or item.get("shortDescription") or "",
    }
