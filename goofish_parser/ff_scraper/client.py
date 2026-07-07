import logging
from typing import Optional

import httpx

GRAPHQL_URL = "https://web-server.production.fruitsfamily.com/graphql"
logger = logging.getLogger(__name__)

_http_client = httpx.AsyncClient(
    headers={
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Origin": "https://fruitsfamily.com",
        "Referer": "https://fruitsfamily.com/",
    },
    timeout=15,
)


async def graphql(query: str, variables: dict | None = None, timeout: int = 15) -> dict:
    payload = {"query": query, "variables": variables or {}}
    try:
        resp = await _http_client.post(GRAPHQL_URL, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        body = e.response.text[:500]
        logger.error(f"GraphQL HTTP {e.response.status_code}: {body}")
        return {"error": f"HTTP {e.response.status_code}: {body}"}
    except Exception as e:
        logger.error(f"GraphQL error: {e}")
        return {"error": str(e)}


SEARCH_QUERY = """
query searchProducts($filter: ProductFilter!, $sort: String!, $limit: Int!) {
    items: searchProducts(filter: $filter, sort: $sort, limit: $limit) {
        id
        title
        brand
        price
        original_price
        status
        size
        condition
        external_url
        resizedSmallImages
        createdAt
        discount_rate
        like_count
        is_visible
        seller {
            id
        }
    }
}
"""

PRODUCT_DETAIL_QUERY = """
query SeeProductResponse($productId: Int!) {
    seeProductResponse(id: $productId) {
        seeProduct {
            id
            title
            brand
            price
            original_price
            description
            status
            size
            condition
            sub_category
            gender
            resizedBigImages
            seller {
                id
                user {
                    username
                    nickname
                }
                rating
                review_count
            }
        }
    }
}
"""

AUTOCOMPLETE_QUERY = """
query GetAutocomplete($query: String!) {
    getAutocomplete(query: $query) {
        brands { id name name_kr }
        search_recommendations { query }
    }
}
"""

CATEGORIES_QUERY = """
query getNavData {
    getCategoriesCached(limit: 200) {
        id
        name
        subcategories {
            id
            name
            gender
        }
    }
}
"""


async def search_products(
    query: str,
    sort: str = "POPULAR",
    limit: int = 30,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    show_only: str = "selling",
) -> list[dict]:
    query_str = query.strip()
    if not query_str:
        return []

    safe_limit = min(limit, 100)
    variables = {
        "filter": {"query": query_str, "show_only": show_only},
        "sort": sort,
        "limit": safe_limit,
    }
    if price_min is not None:
        variables["filter"]["price_min"] = price_min
    if price_max is not None:
        variables["filter"]["price_max"] = price_max

    result = await graphql(SEARCH_QUERY, variables)
    if not isinstance(result, dict):
        logger.error(f"search_products: unexpected result type {type(result)}")
        return []
    if "error" in result:
        logger.error(f"search_products error: {result['error']}")
        return []
    data = result.get("data")
    if not isinstance(data, dict):
        return []
    return data.get("items", [])


async def get_autocomplete(query: str) -> dict:
    result = await graphql(AUTOCOMPLETE_QUERY, {"query": query})
    data = result.get("data") if isinstance(result, dict) else None
    return data.get("getAutocomplete", {}) if isinstance(data, dict) else {}


async def get_categories() -> list[dict]:
    result = await graphql(CATEGORIES_QUERY)
    data = result.get("data") if isinstance(result, dict) else None
    return data.get("getCategoriesCached", []) if isinstance(data, dict) else []


async def get_product_detail(product_id: int) -> dict:
    result = await graphql(PRODUCT_DETAIL_QUERY, {"productId": product_id})
    data = result.get("data") if isinstance(result, dict) else None
    resp = data.get("seeProductResponse", {}) if isinstance(data, dict) else {}
    return resp.get("seeProduct", {}) if isinstance(resp, dict) else {}
